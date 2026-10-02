"""The grounding verifier must catch unsupported claims. Each test plants one hallucination."""

import pytest

from app.grounding.factsheet import FactSheet
from app.grounding.verifier import verify_reply
from app.state import Message, Phase, SessionState
from app.tools import ToolBox


@pytest.fixture
def ctx(repo):
    s = SessionState(phase=Phase.PROCESS_CASE)
    s.verification.status, s.verification.party_id = "verified", "P9"
    s.selected_case_id = "CL-2048"
    s.transcript.append(Message(role="user", content="Why was my claim denied?", turn=1))
    tb = ToolBox(s, repo)
    facts = tb.call("get_claim", case_id="CL-2048")
    facts.merge(tb.call("get_document_guidance", case_id="CL-2048", question="how long after i submit"))
    return s, facts


def check(reply, claims, ctx, repo):
    s, facts = ctx
    return verify_reply(reply, claims, facts, s, repo)


def test_grounded_reply_passes(ctx, repo):
    reply = ("Claim CL-2048 was denied because the review file did not include the pathology report and the "
             "treating provider office note. The appeal deadline on record was 2026-03-18.")
    claims = [{"text": "Claim CL-2048 was denied", "fact_ids": ["claim.CL-2048.case_id", "claim.CL-2048.status"]},
              {"text": "deadline 2026-03-18", "fact_ids": ["claim.CL-2048.appeal_deadline"]}]
    r = check(reply, claims, ctx, repo)
    assert r.ok, r.violations


@pytest.mark.parametrize("reply,needle", [
    ("Your claim will be paid $1,200.00 once you appeal.", "amount"),            # invented amount
    ("You have until April 30, 2026 to appeal.", "date"),                        # invented date
    ("You must appeal within 30 days.", "timeline"),                             # invented timeline
    ("Please also send the repair estimate.", "document"),                       # wrong document
    ("This is similar to claim CL-3001.", "does not belong"),                    # another party's claim
    ("We'll text you at +1 650 521 2836.", "record phone"),                      # PII read-out
    ("Claim CL-9999 is pending.", "not present"),                                # nonexistent case
])
def test_planted_hallucinations_are_caught(ctx, repo, reply, needle):
    r = check(reply, [], ctx, repo)
    assert not r.ok
    assert any(needle in v for v in r.violations), r.violations


def test_citation_to_unknown_fact_is_caught(ctx, repo):
    r = check("It was denied.", [{"text": "It was denied.", "fact_ids": ["claim.CL-2048.secret"]}], ctx, repo)
    assert any("unknown fact id" in v for v in r.violations)


def test_claim_citing_wrong_fact_is_caught(ctx, repo):
    claims = [{"text": "Allowed max is $1450.00", "fact_ids": ["claim.CL-2048.status"]}]
    r = check("The allowed maximum is $1450.00.", claims, ctx, repo)
    assert any("cites facts that do not contain" in v for v in r.violations)


def test_pre_verification_any_claim_detail_is_violation(repo):
    s = SessionState()  # VERIFY_ID, unverified
    s.transcript.append(Message(role="user", content="I'm calling about my denied claim", turn=1))
    facts = FactSheet()
    facts.add("caller.case_hint", "denied claim", "caller")
    for reply in ["Your claim CL-2048 was denied.", "You need to send the pathology report.",
                  "The deadline was 2026-03-18."]:
        assert not verify_reply(reply, [], facts, s, repo).ok, reply


def test_caller_echo_is_allowed(repo):
    s = SessionState()
    s.transcript.append(Message(role="user", content="My DOB is 1985-03-15", turn=1))
    facts = FactSheet()
    assert verify_reply("Thanks, I have your date of birth as 1985-03-15.", [], facts, s, repo).ok
