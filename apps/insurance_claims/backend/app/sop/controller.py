"""The deterministic SOP controller.

Owns phase order, gates and allowed actions. It consumes the LLM's TurnUnderstanding (extraction only),
updates memory, calls phase-allowed tools, and emits a Decision (actions + FactSheet) that the responder
must phrase. The responder can never change the phase or reach data the controller did not fetch.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .. import config
from ..fixtures import Repository
from ..grounding.factsheet import FactSheet
from ..state import MONTHS, PII_FIELDS, Phase, SessionState, Slot
from ..tools import ToolBox, ToolGateError, join_docs, mask_email
from ..understanding import TurnUnderstanding
from ..grounding.extraction_guard import describe_rejections
from .verification import FIELD_LABELS, representative_authorized

NEGATIVE_EMOTIONS = {"frustrated", "angry", "anxious", "confused", "sad"}

INTENT_LABELS = {
    "status_inquiry": "the status of the claim",
    "denial_question": "why the claim was denied",
    "document_submission": "submitting the requested documents",
    "next_steps": "next steps for the claim",
    "payment_question": "payment amounts on the claim",
    "appeal_question": "the appeal deadline",
    "general_claim_question": "general questions about the claim",
}
TOPIC_LABELS = {
    "missing_required_material_alternatives": "alternatives if a requested document is unavailable",
    "submission_timing": "when to submit the documents",
    "processing_time_after_submission": "processing time after submission",
    "submission_method": "how to submit the documents",
    "file_format_requirements": "file format requirements",
    "receipt_confirmation": "how receipt of documents is confirmed",
}


@dataclass
class Decision:
    actions: list[str] = field(default_factory=list)
    facts: FactSheet = field(default_factory=FactSheet)
    question: str | None = None
    used_memory_turns: list[int] = field(default_factory=list)

    def add(self, action: str) -> None:
        if action not in self.actions:
            self.actions.append(action)


# Money questions: answered with each amount under its schema meaning (ANSWER_AMOUNTS).
AMOUNT_QUESTION = re.compile(r"\b(how much|amount|paid|pay|payout|payment|reimburs\w*|maximum|max|allowed|money|"
                             r"cover(ed|age)?|owe|check)\b|\$", re.I)
# "my other claim", "a different one": the caller means a claim other than the one being discussed.
OTHER_CASE = re.compile(r"\b(other|another|different|second)\b(\s+\w+){0,2}\s+(claim|one)\b", re.I)


class SOPController:
    def __init__(self, repo: Repository):
        self.repo = repo

    # ------------------------------------------------------------------------------------------
    def step(self, state: SessionState, und: TurnUnderstanding, message: str,
             rejected: dict[str, str] | None = None) -> Decision:
        d = Decision(question=und.question or (message if "?" in message else None))
        self._rejected = rejected or {}
        tools = ToolBox(state, self.repo)
        self._merge_memory(state, und)
        self._emotion(state, und, d)
        if (hint := state.memory.hint_text()):
            d.facts.add("caller.case_hint", hint, "caller")
        # The agent's own operating rules are facts too, so statements about scope and capabilities are
        # citable and gate-checked instead of improvised (RESEARCH.md: Sierra layer 2, Air Canada).
        d.facts.add("sop.scope", "this line helps only with the caller's insurance policy and claims", "session")
        d.facts.add("sop.human_transfer", "a human representative can be connected at any time on request", "session")
        d.facts.add("session.caller_verified", "yes" if state.verified else "no", "session")
        if state.memory.representative_name:
            d.facts.add("representative.name", state.memory.representative_name.value, "caller")

        if state.phase == Phase.HUMAN_TRANSFER:
            d.add("ALREADY_TRANSFERRED")
            d.facts.add("transfer.reason", state.transfer_reason, "session")
            return d

        # A pending "shall I transfer you?" offer is answered first.
        if state.pending_offer == "human_transfer":
            if und.affirmation == "yes" or und.wants_human:
                return self._transfer(state, tools, d, state.transfer_reason or "caller accepted transfer")
            if und.affirmation == "no":
                state.pending_offer = None
                state.transfer_reason = None
                d.add("TRANSFER_DECLINED")
        if und.wants_human:
            return self._transfer(state, tools, d, "caller asked for a human representative")

        if und.is_injection_attempt:
            state.counters.injection_attempts += 1
            state.log("guardrail", kind="injection_attempt", verified=state.verified)
            # Verified callers keep their (own-claim) access; only the override itself is refused.
            d.add("INJECTION_NOTED" if state.verified else "INJECTION_REFUSAL")

        # Pushing back on a refused off-topic request ("act as an answering machine") is a retry, not a reset.
        scope_retry = und.is_off_topic or (und.is_injection_attempt and state.counters.off_topic_streak > 0)
        if scope_retry:
            state.counters.off_topic_streak += 1
            state.counters.off_topic_total += 1
            state.log("guardrail", kind="off_topic", streak=state.counters.off_topic_streak)
            d.add("OFF_TOPIC_REFUSAL")
            if state.counters.off_topic_streak >= config.OFF_TOPIC_OFFER_HUMAN_AFTER:
                self._offer_human(state, d, "repeated questions outside insurance claim support")
            if not self._has_task_content(und, state):
                self._phase_nudge(state, d)
                return d
        elif und.is_injection_attempt and not self._has_task_content(und, state):
            self._phase_nudge(state, d)
            return d
        if scope_retry and state.phase != Phase.VERIFY_ID and not (
                und.followup_topics or und.case_id or und.is_done or und.email_choice):
            # Pushback after an off-topic refusal is not a claim question, even if the model tagged an intent.
            self._phase_nudge(state, d)
            return d
        else:
            state.counters.off_topic_streak = 0

        handler = {
            Phase.VERIFY_ID: self._verify_id,
            Phase.RESOLVE_INTENT: self._resolve_intent,
            Phase.PROCESS_CASE: self._process_case,
            Phase.POST_PROCESS: self._post_process,
            Phase.ENDED: self._ended,
        }[state.phase]
        return handler(state, und, d, tools, message)

    # ------------------------------------------------------------------------------------------
    # Memory: store everything useful whenever it is said, even if it belongs to a later phase.
    def _merge_memory(self, state: SessionState, und: TurnUnderstanding) -> None:
        m, t = state.memory, state.turn
        changed: dict[str, Any] = {}
        for fname, value in {"name": und.full_name, "dob": und.dob, "phone": und.phone,
                             "email": und.email, "id_last4": und.id_last4}.items():
            if value and (fname not in m.pii or m.pii[fname].value != value):
                previous = m.pii.get(fname) or state.verification.retained_pii.get(fname)
                if previous and previous.value != value:
                    state.log("field_corrected", field=fname)  # field name only, never the values
                m.pii[fname] = Slot(value=value, turn=t)
                changed[fname] = "<redacted>"
        for key, value in {"policy_number": und.policy_number, "caller_role": und.caller_role,
                           "representative_name": und.representative_name,
                           "representative_relationship": und.representative_relationship,
                           "intent": und.intent}.items():
            if m.set(key, value, t):
                changed[key] = value
        for key, value in {"case_id": und.case_id, "case_type": und.case_type, "status": und.case_status,
                           "month": und.case_month, "year": und.case_year}.items():
            if value and (key not in m.case_hints or m.case_hints[key].value != value):
                m.case_hints[key] = Slot(value=value, turn=t)
                changed[f"case_hint.{key}"] = value
        for topic in und.followup_topics:
            if topic not in [s.value for s in m.followup_topics]:
                m.followup_topics.append(Slot(value=topic, turn=t))
                changed.setdefault("followup_topics", []).append(topic)
        for note in und.caller_notes:
            m.caller_notes.append(Slot(value=note, turn=t))
            changed.setdefault("caller_notes", []).append(note)
        if und.lacks_document and m.set("lacks_document", True, t):
            changed["lacks_document"] = True
        if und.cannot_obtain_alternatives and m.set("cannot_obtain_alternatives", True, t):
            changed["cannot_obtain_alternatives"] = True
        if changed:
            state.log("memory_update", phase=state.phase.value, changed=changed)

    def _emotion(self, state: SessionState, und: TurnUnderstanding, d: Decision) -> None:
        closing = und.is_done or bool(und.email_choice)
        if (und.emotion in NEGATIVE_EMOTIONS and not closing) or und.refuses_verification:
            state.counters.frustration_streak += 1
            d.add("EMPATHY")
            d.facts.add("caller.emotion", und.emotion if und.emotion != "neutral" else "frustrated", "caller")
        else:
            state.counters.frustration_streak = 0

    @staticmethod
    def _has_task_content(und: TurnUnderstanding, state: SessionState) -> bool:
        # A bare yes/no is only task content when it answers a pending offer ("No, act as…" is not).
        answers_offer = bool(state.pending_offer) and bool(und.affirmation or und.email_choice)
        return any([und.full_name, und.dob, und.phone, und.email, und.id_last4, und.policy_number,
                    und.case_id, und.case_type, und.case_status, und.intent, und.followup_topics,
                    und.is_done, answers_offer])

    def _phase_nudge(self, state: SessionState, d: Decision) -> None:
        if state.phase == Phase.VERIFY_ID:
            self._ask_verification_facts(state, d)
        elif state.selected_case_id:
            d.facts.add("session.selected_case_id", state.selected_case_id, "session")

    def _offer_human(self, state: SessionState, d: Decision, reason: str) -> None:
        if state.pending_offer != "human_transfer":
            state.pending_offer = "human_transfer"
            state.transfer_reason = reason
            state.log("offer", kind="human_transfer", reason=reason)
        d.add("OFFER_HUMAN")
        d.facts.add("offer.human_transfer_reason", reason, "session")

    def _transfer(self, state: SessionState, tools: ToolBox, d: Decision, reason: str) -> Decision:
        state.transfer_reason = reason
        state.pending_offer = None
        state.set_phase(Phase.HUMAN_TRANSFER, reason)
        d.facts.merge(tools.call("transfer_to_human", reason=reason))
        d.add("TRANSFER_HUMAN")
        return d

    # ------------------------------------------------------------------------------------------
    # VERIFY_ID: strict. No claim data, no advancing until >= 3 PII fields match one record.
    def _verify_id(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
                   message: str) -> Decision:
        v = state.verification
        if v.status == "verified" and state.consent.required:
            return self._consent_step(state, und, d, tools)

        if und.refuses_verification:
            state.counters.verification_refusals += 1
            d.add("EXPLAIN_VERIFICATION")
            if (state.counters.verification_refusals >= config.REFUSALS_OFFER_HUMAN_AFTER
                    or state.counters.frustration_streak >= config.FRUSTRATION_OFFER_HUMAN_AFTER):
                self._offer_human(state, d, "caller is unable or unwilling to complete identity verification")

        unclear = describe_rejections(self._rejected)
        if unclear:
            # Values we could not ground in the caller's words are asked about, never guessed or counted.
            d.add("CLARIFY_FIELDS")
            d.facts.add("verification.unclear_fields", unclear, "caller")

        # A correction after a failed match ("sorry, my DOB is ...") re-uses the other fields from that
        # attempt. Only new identity input re-runs the match; a bare "why?" does not.
        fresh = [s for s in state.memory.pii.values() if s.turn == state.turn]
        if v.retained_pii and 0 < len(fresh) < config.MIN_VERIFIED_FIELDS:
            for f, slot in v.retained_pii.items():
                state.memory.pii.setdefault(f, slot)
        provided = {k: s.value for k, s in state.memory.pii.items()}
        policy = state.memory.policy_number.value if state.memory.policy_number else None
        if len(provided) < config.MIN_VERIFIED_FIELDS:
            d.add("ASK_VERIFICATION")
            self._ask_verification_facts(state, d)
            return d

        facts = tools.call("verify_identity", provided=provided, policy_number=policy)
        result = tools._last_verification
        if result.outcome == "verified":
            v.status, v.party_id, v.matched_fields = "verified", result.party_id, result.matched_fields
            v.retained_pii = {}
            state.log("verified", party_id=result.party_id, matched_fields=result.matched_fields)
            d.facts.merge(facts)
            d.add("VERIFIED")
            if state.memory.caller_role and state.memory.caller_role.value == "representative":
                rep_name = state.memory.representative_name.value if state.memory.representative_name else None
                rel = state.memory.representative_relationship.value if state.memory.representative_relationship else None
                rep = representative_authorized(rep_name, rel, result.party_id, self.repo)
                if not rep:
                    v.status = "unverified"  # keep the gate closed
                    state.log("representative_rejected", reason="not an authorized representative on file")
                    d.actions.remove("VERIFIED")
                    d.add("REP_NOT_AUTHORIZED")
                    self._offer_human(state, d, "caller is not an authorized representative on file")
                    return d
                state.consent.required = True
                state.log("representative_identified", relationship=rep["relationship"])
                d.facts.add("representative.relationship", rep["relationship"], "session")
                return self._consent_step(state, und, d, tools)
            state.set_phase(Phase.RESOLVE_INTENT, "identity verified")
            return self._resolve_intent(state, und, d, tools, message)

        # Failed: count each distinct combination once, clear the identity slots, never say which field.
        signature = hashlib.sha256(repr(sorted(provided.items())).encode()).hexdigest()[:16]
        if signature not in v.failed_signatures:
            v.failed_signatures.append(signature)
            v.failed_attempts += 1
        v.retained_pii = dict(state.memory.pii)
        state.memory.pii.clear()
        state.log("verification_failed", attempts=v.failed_attempts)
        if v.failed_attempts >= config.MAX_FAILED_VERIFICATIONS:
            v.status = "locked"
            state.log("verification_locked")
            d.add("VERIFICATION_LOCKED")
            return self._transfer(state, tools, d, "identity could not be verified after several attempts")
        d.add("VERIFICATION_FAILED")
        d.facts.add("verification.correction", "the caller can correct any single detail they gave; the "
                    "other details from this attempt are kept for the next check", "session")
        d.facts.add("verification.attempts_remaining", config.MAX_FAILED_VERIFICATIONS - v.failed_attempts, "session")
        self._ask_verification_facts(state, d, after_failure=True)
        return d

    def _ask_verification_facts(self, state: SessionState, d: Decision, after_failure: bool = False) -> None:
        have = set() if after_failure else set(state.memory.pii)
        remaining = [FIELD_LABELS[f] for f in PII_FIELDS if f not in have]
        need = max(config.MIN_VERIFIED_FIELDS - len(have), 0)
        d.facts.add("verification.rule", "identity is verified with at least 3 of: full name, date of birth, "
                    "phone number, email address, last 4 digits of SSN or national ID", "session")
        d.facts.add("verification.fields_still_needed", need, "session")
        d.facts.add("verification.fields_received", len(have), "session")
        d.facts.add("verification.options_remaining", remaining, "session")
        d.facts.add("sop.after_verification", "once identity is verified, the agent looks up the claim the caller "
                    "described", "session")
        d.facts.add("verification.why", "claim details are protected health and financial information, and "
                    "verifying identity keeps them from being shared with the wrong person", "session")
        if state.verification.retained_pii and not after_failure:
            d.facts.add("verification.last_attempt", "the details from the last attempt did not match our records; "
                        "for security the agent does not say which detail", "session")
            d.facts.add("verification.correction", "the caller can correct any single detail they gave; the "
                        "other details from that attempt are kept for the next check", "session")

    def _consent_step(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox) -> Decision:
        d.facts.merge(tools.call("check_consent"))
        status = state.consent.status
        state.log("consent_status", status=status, polls=state.consent.polls)
        if status == "approved":
            d.add("CONSENT_APPROVED")
            state.set_phase(Phase.RESOLVE_INTENT, "identity verified and policyholder consent approved")
            return self._resolve_intent(state, und, d, tools, "")
        if status == "timeout":
            d.add("CONSENT_TIMEOUT")
            return self._transfer(state, tools, d, "policyholder consent was not received in time")
        d.add("CONSENT_PENDING")
        return d

    # ------------------------------------------------------------------------------------------
    # RESOLVE_INTENT: use remembered hints instead of asking from scratch.
    def _score(self, claim: dict[str, Any], hints: dict[str, Slot], intent: str | None) -> float:
        h = {k: s.value for k, s in hints.items()}
        if h.get("case_id"):
            return 100.0 if claim["case_id"].upper() == str(h["case_id"]).upper() else float("-inf")
        score = 0.0
        if "case_type" in h:
            if claim["case_type"] != h["case_type"]:
                return float("-inf")
            score += 3
        if "status" in h:
            if claim["status"] != h["status"]:
                return float("-inf")
            score += 3
        created = claim["created_at"]
        if "month" in h:
            if int(created[5:7]) != int(h["month"]):
                return float("-inf")
            score += 2
        if "year" in h:
            if int(created[:4]) != int(h["year"]):
                return float("-inf")
            score += 1
        if intent == "denial_question" and claim["status"] == "denied":
            score += 1
        return score

    def _resolve_intent(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
                        message: str) -> Decision:
        d.facts.merge(tools.call("list_claims"))
        claims = self.repo.claims_for(state.verification.party_id)
        hints = state.memory.case_hints
        intent = state.memory.intent.value if state.memory.intent else None
        if not claims:
            d.facts.add("claims.count", 0, "session")
            d.add("NO_CLAIMS_ON_FILE")
            return d
        if len(claims) == 1 and not hints.get("case_id"):
            return self._select_case(state, und, d, tools, claims[0]["case_id"], message)
        if not hints and not intent:
            state.candidate_case_ids = [c["case_id"] for c in claims]
            d.add("ASK_INTENT")
            return d

        scored = sorted(((self._score(c, hints, intent), c) for c in claims), key=lambda x: -x[0])
        best = scored[0][0]
        top = [c for s, c in scored if s == best and s > float("-inf")]
        if best > 0 and len(top) == 1:
            return self._select_case(state, und, d, tools, top[0]["case_id"], message)
        if top and best > float("-inf"):
            state.candidate_case_ids = [c["case_id"] for c in top]
            d.facts.add("resolve.candidates", state.candidate_case_ids, "session")
            d.add("DISAMBIGUATE")
            return d
        state.candidate_case_ids = [c["case_id"] for c in claims]
        d.facts.add("resolve.no_match_for", state.memory.hint_text() or intent, "caller")
        d.add("NO_MATCHING_CASE")
        return d

    def _select_case(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
                     case_id: str, message: str) -> Decision:
        # The case hints say which claim; the intent only counts when there are none (a stale turn-1 intent
        # made a later "what about my auto claim?" read as "based on what you mentioned earlier").
        hint_turns = sorted({s.turn for s in state.memory.case_hints.values()}
                            or ({state.memory.intent.turn} if state.memory.intent else set()))
        state.selected_case_id = case_id
        state.candidate_case_ids = []
        d.used_memory_turns = [t for t in hint_turns if t < state.turn]
        state.log("case_selected", case_id=case_id, hints=state.memory.hint_text(), hint_turns=hint_turns,
                  used_memory_from_earlier_turns=bool(d.used_memory_turns))
        d.facts.add("session.selected_case_id", case_id, "session")
        if d.used_memory_turns:
            d.facts.add("session.case_found_from_earlier_hint", state.memory.hint_text(), "caller")
        d.add("CASE_SELECTED")
        state.set_phase(Phase.PROCESS_CASE, f"case {case_id} resolved")
        return self._answer_case(state, und, d, tools, message)

    # ------------------------------------------------------------------------------------------
    # PROCESS_CASE: flexible, but only grounded claim/guideline facts reach the responder.
    def _process_case(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
                      message: str) -> Decision:
        new_question = und.followup_topics or (und.question and "?" in message)
        if und.is_done and not new_question:
            return self._offer_email(state, d, tools)
        # Caller referred to a claim this turn ("what about my auto claim?", "back to the denied one", "my
        # other one")? Match on what was said THIS turn only: memory keeps the earlier description, and
        # mixing them produced "your denied auto claim from January" for a caller who only said "auto".
        said = {k: v for k, v in {"case_id": und.case_id, "case_type": und.case_type, "status": und.case_status,
                                  "month": und.case_month, "year": und.case_year}.items() if v}
        other = bool(OTHER_CASE.search(message))
        if said or other:
            claims = self.repo.claims_for(state.verification.party_id)
            turn_hints = {k: Slot(value=v, turn=state.turn) for k, v in said.items()}
            matches = [c for c in claims if self._score(c, turn_hints, None) > float("-inf")
                       and not (other and c["case_id"] == state.selected_case_id)]
            if matches and not any(c["case_id"] == state.selected_case_id for c in matches):
                # The new reference replaces the old description of which claim this call is about.
                state.memory.case_hints = turn_hints
                state.log("case_reference_changed", hints=sorted(said), other=other,
                          candidates=[c["case_id"] for c in matches])
                if len(matches) == 1:
                    state.log("case_switched", from_case=state.selected_case_id, to_case=matches[0]["case_id"])
                    d.facts.add("session.switched_from_case_id", state.selected_case_id, "session")
                    return self._select_case(state, und, d, tools, matches[0]["case_id"], message)
                state.set_phase(Phase.RESOLVE_INTENT, "caller referred to a different claim that matches several")
                d.facts.merge(tools.call("list_claims"))
                state.candidate_case_ids = [c["case_id"] for c in matches]
                d.facts.add("resolve.candidates", state.candidate_case_ids, "session")
                d.add("DISAMBIGUATE")
                return d
            if not matches:
                # e.g. another policyholder's claim id: do not confirm or deny it exists.
                d.facts.merge(tools.call("list_claims"))
                state.candidate_case_ids = [c["case_id"] for c in claims]
                d.facts.add("resolve.no_match_for", " ".join(
                    str(s.value) for s in turn_hints.values()), "caller")
                d.add("NO_MATCHING_CASE")
                return d
        return self._answer_case(state, und, d, tools, message)

    def _answer_case(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
                     message: str) -> Decision:
        case_id = state.selected_case_id
        try:
            d.facts.merge(tools.call("get_claim", case_id=case_id))
        except ToolGateError:
            d.add("CASE_UNAVAILABLE")
            return d
        if und.intent == "payment_question" or AMOUNT_QUESTION.search(message):
            d.add("ANSWER_AMOUNTS")
        topics = [s.value for s in state.memory.followup_topics if s.turn == state.turn]
        lacks = bool(state.memory.lacks_document) and (
            state.memory.lacks_document.turn == state.turn or bool(und.lacks_document))
        guidance = tools.call("get_document_guidance", case_id=case_id, question=message,
                              topics=topics, lacks_document=lacks)
        d.facts.merge(guidance)
        matched_topics = [fid.split(".", 2)[2] for fid in guidance.facts if fid.startswith("guide.topic.")]
        for item in [*(INTENT_LABELS.get(state.memory.intent.value, "") for _ in [0] if state.memory.intent),
                     *(TOPIC_LABELS[t] for t in matched_topics)]:
            if item and item not in state.discussed_topics:
                state.discussed_topics.append(item)
        if state.memory.cannot_obtain_alternatives and state.alternatives_offered:
            self._offer_human(state, d, "requested documents and reasonable alternatives cannot be obtained")
        if lacks:
            state.alternatives_offered = True
        d.add("ANSWER_CASE")
        return d

    # ------------------------------------------------------------------------------------------
    # POST_PROCESS: offer an email summary; the caller chooses send or skip.
    def build_email_summary(self, state: SessionState) -> dict[str, Any]:
        record = self.repo.policyholder(state.verification.party_id)
        claim = self.repo.claim(state.selected_case_id) if state.selected_case_id else None
        g = self.repo.guideline
        summary: dict[str, Any] = {
            "subject": f"Summary of your call about claim {claim['case_id']}" if claim else "Summary of your call",
            "greeting": f"Hello {record['name']},",
            "discussed": state.discussed_topics or ["your claims on file"],
            "claim": None, "next_steps": [],
        }
        if claim:
            summary["claim"] = {k: claim[k] for k in ("case_id", "case_type", "status", "summary", "created_at")}
            if claim.get("denial_reason"):
                summary["claim"]["denial_reason"] = claim["denial_reason"]
            docs = claim.get("documents_needed", [])
            if docs:
                summary["next_steps"].append(
                    f"Submit {join_docs(docs)} for claim {claim['case_id']} through the member portal or claim upload link.")
                summary["next_steps"].append(
                    "Average processing time after submission: "
                    + g["claim_followup_settings"]["average_processing_time_after_submission"]["en"] + ".")
            if claim.get("appeal_deadline"):
                status = "passed" if claim["appeal_deadline"] < config.today().isoformat() else "upcoming"
                summary["next_steps"].append(f"Appeal deadline on record: {claim['appeal_deadline']} ({status}).")
            if state.transfer_reason:
                summary["next_steps"].append("A human representative will follow up on: " + state.transfer_reason + ".")
            if not summary["next_steps"]:
                summary["next_steps"].append("No action is needed from you on this claim right now.")
        return summary

    def _offer_email(self, state: SessionState, d: Decision, tools: ToolBox) -> Decision:
        state.set_phase(Phase.POST_PROCESS, "caller has no further questions")
        summary = self.build_email_summary(state)
        state.email.offered, state.email.preview = True, summary
        state.pending_offer = "email"
        state.log("offer", kind="email_summary")
        record = self.repo.policyholder(state.verification.party_id)
        d.facts.add("email.to_masked", mask_email(record["email"]), "policyholder_record")
        d.facts.add("email.summary_subject", summary["subject"], "session")
        d.facts.add("email.summary_contents", "what was discussed, the claim status and outcome, and the next steps",
                    "session")
        d.facts.add("email.summary_topics", summary["discussed"], "session")
        d.facts.add("email.summary_next_steps", summary["next_steps"], "session")
        if state.selected_case_id:
            d.facts.merge(tools.call("get_claim", case_id=state.selected_case_id))
        d.add("OFFER_EMAIL")
        return d

    def _post_process(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
                      message: str) -> Decision:
        choice = und.email_choice or ({"yes": "send", "no": "skip"}.get(und.affirmation or "")
                                      if state.pending_offer == "email" else None)
        if choice == "send":
            state.email.choice = "send"
            state.pending_offer = None
            d.facts.merge(tools.call("send_email_summary", summary=state.email.preview or self.build_email_summary(state)))
            state.log("email_sent", to=state.email.sent_to)
            d.add("EMAIL_SENT")
            state.set_phase(Phase.ENDED, "email summary sent")
            return d
        if choice == "skip":
            state.email.choice = "skip"
            state.pending_offer = None
            state.log("email_skipped")
            d.facts.add("email.status", "not sent, because the caller chose to skip it", "session")
            d.add("EMAIL_SKIPPED")
            state.set_phase(Phase.ENDED, "caller skipped the email summary")
            return d
        if und.question or und.followup_topics or und.case_id or und.intent:
            state.pending_offer = None
            state.set_phase(Phase.PROCESS_CASE, "caller asked another claim question")
            return self._process_case(state, und, d, tools, message)
        return self._offer_email(state, d, tools)

    def _ended(self, state: SessionState, und: TurnUnderstanding, d: Decision, tools: ToolBox,
               message: str) -> Decision:
        if state.verified and (und.question or und.followup_topics or und.case_id or und.intent):
            state.set_phase(Phase.PROCESS_CASE, "caller reopened with another claim question")
            return self._process_case(state, und, d, tools, message)
        d.add("GOODBYE")
        return d


def month_name(n: int) -> str:
    return MONTHS[n - 1]
