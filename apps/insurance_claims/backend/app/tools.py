"""Phase-gated tools. Tools are selected by the SOP controller, never by the LLM, and every call
is checked against the phase allow-list and the verification gate before it runs."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Callable

from . import config
from .fixtures import Repository
from .grounding.factsheet import FactSheet
from .sop import verification as ver
from .state import Phase, SessionState

ALLOWED_TOOLS: dict[Phase, set[str]] = {
    Phase.VERIFY_ID: {"verify_identity", "check_consent", "transfer_to_human"},
    Phase.RESOLVE_INTENT: {"list_claims", "get_claim", "transfer_to_human"},
    Phase.PROCESS_CASE: {"list_claims", "get_claim", "get_document_guidance", "transfer_to_human"},
    Phase.POST_PROCESS: {"get_claim", "get_document_guidance", "send_email_summary", "transfer_to_human"},
    Phase.HUMAN_TRANSFER: {"transfer_to_human"},
    Phase.ENDED: set(),
}
REQUIRES_VERIFIED = {"list_claims", "get_claim", "get_document_guidance", "send_email_summary"}

MONEY_FIELDS = ("expected_reimbursement_amount", "allowed_max_amount", "net_pay", "net_fee")


class ToolGateError(RuntimeError):
    pass


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}" if local else email


def join_docs(docs: list[str]) -> str:
    docs = [f"the {d}" for d in docs]
    if len(docs) <= 1:
        return "".join(docs)
    return ", ".join(docs[:-1]) + " and " + docs[-1]


def resolve_document_key(doc: str, guidance: dict[str, Any]) -> str | None:
    """Map a claim's document name to its guideline key ("pathology report" -> "original pathology report")."""
    d = ver.normalize_name(doc)
    if doc in guidance:
        return doc
    for key in guidance:
        k = ver.normalize_name(key)
        if d in k or k in d:
            return key
    return None


class ToolBox:
    def __init__(self, state: SessionState, repo: Repository):
        self.state = state
        self.repo = repo

    def call(self, name: str, **kwargs: Any) -> FactSheet:
        allowed = ALLOWED_TOOLS.get(self.state.phase, set())
        if name not in allowed:
            self.state.log("tool_blocked", tool=name, phase=self.state.phase.value, reason="not allowed in phase")
            raise ToolGateError(f"{name} is not allowed in {self.state.phase.value}")
        if name in REQUIRES_VERIFIED and not self.state.verified:
            self.state.log("tool_blocked", tool=name, phase=self.state.phase.value, reason="caller not verified")
            raise ToolGateError(f"{name} requires a verified caller")
        fn: Callable[..., FactSheet] = getattr(self, f"_{name}")
        facts = fn(**kwargs)
        args = {"fields": sorted(kwargs["provided"])} if name == "verify_identity" else _jsonable(kwargs)
        self.state.log("tool_call", tool=name, args=args, fact_ids=list(facts.facts))
        return facts

    # --- identity -----------------------------------------------------------------------------

    def _verify_identity(self, provided: dict[str, str], policy_number: str | None) -> FactSheet:
        result = ver.verify(provided, self.repo, policy_number)
        facts = FactSheet()
        facts.add("verification.outcome", result.outcome, "session")
        facts.add("verification.fields_provided_count", len(result.provided_fields), "session")
        if result.outcome == "verified":
            record = self.repo.policyholder(result.party_id)
            facts.add("policyholder.name", record["name"], "policyholder_record")
            facts.add("policyholder.policy_number", record["policy_number"], "policyholder_record")
            facts.add("policyholder.email_masked", mask_email(record["email"]), "policyholder_record")
        self._last_verification = result
        return facts

    def _check_consent(self) -> FactSheet:
        consent = self.state.consent
        sequence = self.repo.consent_scenarios.get(consent.scenario, self.repo.consent_scenarios["default"])["status_sequence"]
        if consent.polls < len(sequence):
            status = sequence[consent.polls]
        else:
            status = "timeout"
        consent.polls += 1
        if status == "pending" and consent.polls >= len(sequence) and sequence[-1] == "pending":
            status = "timeout"
        consent.status = status  # type: ignore[assignment]
        facts = FactSheet()
        facts.add("consent.status", status, "session")
        facts.add("consent.method", "a consent request to the policyholder's phone number on file", "session")
        return facts

    def _transfer_to_human(self, reason: str) -> FactSheet:
        facts = FactSheet()
        facts.add("transfer.reason", reason, "session")
        facts.add("transfer.next", "a human customer service representative will join this conversation", "session")
        return facts

    # --- claims -------------------------------------------------------------------------------

    def _list_claims(self) -> FactSheet:
        facts = FactSheet()
        for c in self.repo.claims_for(self.state.verification.party_id):
            p = f"claim.{c['case_id']}"
            facts.add(f"{p}.case_id", c["case_id"], "claim_record")
            facts.add(f"{p}.case_type", c["case_type"], "claim_record")
            facts.add(f"{p}.created_at", c["created_at"], "claim_record")
            facts.add(f"{p}.status", c["status"], "claim_record")
            facts.add(f"{p}.summary", c["summary"], "claim_record")
        return facts

    def _get_claim(self, case_id: str) -> FactSheet:
        claim = self.repo.claim(case_id)
        if not claim or claim["party_id"] != self.state.verification.party_id:
            self.state.log("tool_blocked", tool="get_claim", reason="claim not owned by verified party")
            raise ToolGateError("claim not found for this policyholder")
        facts = FactSheet()
        p = f"claim.{claim['case_id']}"
        for key, value in claim.items():
            if key != "party_id":
                facts.add(f"{p}.{key}", value, "claim_record")
        for key in MONEY_FIELDS:
            desc = self.repo.claim_schema["field_descriptions"].get(key, {}).get("description")
            facts.add(f"schema.{key}", desc, "schema")
        if claim.get("appeal_deadline"):
            today = config.today()
            deadline = date.fromisoformat(claim["appeal_deadline"])
            facts.add("session.today", today.isoformat(), "session")
            facts.add(f"{p}.appeal_deadline_status",
                      "passed" if deadline < today else f"open ({(deadline - today).days} days remaining)", "derived")
        if not claim.get("denial_reason"):
            facts.add(f"{p}.denial_reason_on_record", "none (this claim has no denial reason on record)", "derived")
        if not claim.get("documents_needed"):
            facts.add(f"{p}.documents_needed_on_record", "none (no documents are requested for this claim)", "derived")
        return facts

    def _get_document_guidance(self, case_id: str, question: str = "", topics: list[str] | None = None,
                               lacks_document: bool = False) -> FactSheet:
        claim = self.repo.claim(case_id)
        if not claim or claim["party_id"] != self.state.verification.party_id:
            raise ToolGateError("claim not found for this policyholder")
        g = self.repo.guideline
        docs: list[str] = claim.get("documents_needed", [])
        facts = FactSheet()
        facts.add("guide.default", g["default_guidance"]["en"], "guideline")
        if (ct := g["case_type_guidance"].get(claim["case_type"])):
            facts.add(f"guide.case_type.{claim['case_type']}", ct["en"], "guideline")

        q = question.casefold()
        # Alternatives only for the document(s) the caller says are missing (all if unspecified).
        named = [d for d in docs if d.casefold() in q or d.split()[0].casefold() in q]
        lacking = named or docs
        for doc in docs:
            key = resolve_document_key(doc, g["document_guidance"])
            if key:
                facts.add(f"guide.document.{doc}", g["document_guidance"][key]["en"], "guideline")
            if lacks_document and doc in lacking:
                alt_key = resolve_document_key(doc, g["document_alternative_guidance"]) or "default"
                facts.add(f"guide.alternative.{doc}", g["document_alternative_guidance"][alt_key]["en"], "guideline")
        if lacks_document and docs:
            facts.add("guide.human_review_after_alternatives",
                      g["claim_followup_settings"]["human_review_after_document_alternatives_exhausted"]["en"], "guideline")

        wanted = set(topics or [])
        matched: list[str] = []
        values = {
            "case_id": claim["case_id"],
            "documents": join_docs(docs),
            "average_processing_time_after_submission":
                g["claim_followup_settings"]["average_processing_time_after_submission"]["en"],
        }
        for entry in g["claim_followup_guidance"]:
            if entry.get("requires_documents") and not docs:
                continue
            hit = entry["topic"] in wanted or any(phrase in q for phrase in entry.get("match_any", []))
            if entry["topic"] == "missing_required_material_alternatives" and lacks_document:
                hit = True
            if hit:
                matched.append(entry["topic"])
                facts.add(f"guide.topic.{entry['topic']}", entry["en"].format(**values), "guideline")
        if q and not matched and docs:
            facts.add("guide.fallback", g["claim_followup_fallback"]["en"], "guideline")
        facts.add("guide.average_processing_time", values["average_processing_time_after_submission"], "guideline")
        return facts

    # --- post process -------------------------------------------------------------------------

    def _send_email_summary(self, summary: dict[str, Any]) -> FactSheet:
        record = self.repo.policyholder(self.state.verification.party_id)
        config.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = config.OUTBOX_DIR / f"{stamp}-{self.state.id}.json"
        path.write_text(json.dumps({"to": record["email"], **summary}, indent=2))
        facts = FactSheet()
        facts.add("email.sent_to_masked", mask_email(record["email"]), "session")
        facts.add("email.status", "sent", "session")
        self.state.email.sent_to = mask_email(record["email"])
        return facts


def _jsonable(obj: Any) -> Any:
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)
