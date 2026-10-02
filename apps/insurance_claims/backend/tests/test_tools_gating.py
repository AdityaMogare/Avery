"""Deterministic guards: claim tools are unavailable until verified, and only for the caller's own claims."""

import pytest

from app.state import Phase, SessionState
from app.tools import ToolBox, ToolGateError, resolve_document_key


def verified_state(party="P9") -> SessionState:
    s = SessionState()
    s.verification.status, s.verification.party_id = "verified", party
    return s


@pytest.mark.parametrize("tool,kwargs", [("list_claims", {}), ("get_claim", {"case_id": "CL-2048"})])
def test_claim_tools_blocked_in_verify_id(repo, tool, kwargs):
    s = SessionState()
    with pytest.raises(ToolGateError):
        ToolBox(s, repo).call(tool, **kwargs)
    assert s.trace[-1].type == "tool_blocked"


def test_claim_tools_blocked_if_not_verified_even_in_later_phase(repo):
    s = SessionState(phase=Phase.PROCESS_CASE)  # phase forced, but no verification
    with pytest.raises(ToolGateError, match="verified"):
        ToolBox(s, repo).call("get_claim", case_id="CL-2048")


def test_representative_needs_consent_before_claims(repo):
    s = verified_state()
    s.phase = Phase.RESOLVE_INTENT
    s.consent.required, s.consent.status = True, "pending"
    with pytest.raises(ToolGateError):
        ToolBox(s, repo).call("list_claims")


def test_get_claim_enforces_ownership(repo):
    s = verified_state("P9")
    s.phase = Phase.PROCESS_CASE
    with pytest.raises(ToolGateError):
        ToolBox(s, repo).call("get_claim", case_id="CL-3001")  # belongs to P12


def test_get_claim_facts_and_derived_deadline(repo, monkeypatch):
    s = verified_state()
    s.phase = Phase.PROCESS_CASE
    facts = ToolBox(s, repo).call("get_claim", case_id="CL-2048")
    assert facts.get("claim.CL-2048.status").value == "denied"
    assert facts.get("claim.CL-2048.appeal_deadline_status").value == "passed"  # AGENT_TODAY=2026-10-01
    assert "party_id" not in " ".join(facts.facts)


def test_document_alias_mapping(repo):
    g = repo.guideline["document_guidance"]
    assert resolve_document_key("pathology report", g) == "original pathology report"
    assert resolve_document_key("office note", g) == "treating provider office note"
    assert resolve_document_key("diagnosis report", g) is None


def test_guidance_topics_match_and_fill_placeholders(repo):
    s = verified_state()
    s.phase = Phase.PROCESS_CASE
    facts = ToolBox(s, repo).call("get_document_guidance", case_id="CL-2048", question="How long does it take after I submit?")
    topic = facts.get("guide.topic.processing_time_after_submission").value
    assert "CL-2048" in topic and "usually less than a week" in topic and "{" not in topic


def test_alternatives_only_for_named_document(repo):
    s = verified_state()
    s.phase = Phase.PROCESS_CASE
    facts = ToolBox(s, repo).call("get_document_guidance", case_id="CL-2048",
                                  question="I don't have the pathology report", lacks_document=True)
    assert "guide.alternative.pathology report" in facts
    assert "guide.alternative.office note" not in facts


def test_verify_identity_trace_has_no_pii_values(repo):
    s = SessionState()
    ToolBox(s, repo).call("verify_identity", provided={"name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"},
                          policy_number=None)
    assert "4472" not in str(s.trace[-1].data) and "1985" not in str(s.trace[-1].data)
