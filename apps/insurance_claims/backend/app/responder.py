"""Response generation.

LLMResponder phrases the controller's Decision from the FactSheet (with citations).
TemplateResponder renders the same Decision deterministically. It is the offline mode and the safe
fallback when an LLM reply fails grounding verification twice (Parlant's "strict" composition idea).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .grounding.factsheet import FactSheet
from .prompts import build_system_prompt
from .sop.controller import Decision
from .state import SessionState


class Claim(BaseModel):
    text: str
    fact_ids: list[str] = Field(default_factory=list)


class ResponseDraft(BaseModel):
    rule_check: str = ""
    reply: str
    claims: list[Claim] = Field(default_factory=list)


class LLMResponder:
    def __init__(self, llm):
        self.llm = llm

    def respond(self, state: SessionState, decision: Decision, message: str,
                violations: list[str] | None = None) -> ResponseDraft:
        system = build_system_prompt(state.phase, decision.actions)
        history = [{"role": m.role, "content": m.content} for m in state.transcript[-9:-1]]
        retry = ""
        if violations:
            retry = ("\n\nYOUR PREVIOUS DRAFT WAS REJECTED by the grounding verifier for: "
                     + "; ".join(violations) + ". Rewrite it using only FACTS and cite correctly.")
        user = (f"FACTS (the only allowed source of factual statements):\n{decision.facts.render()}\n\n"
                f"CALLER'S LATEST MESSAGE: {message}{retry}")
        return self.llm.structured(system, [*history, {"role": "user", "content": user}], ResponseDraft, "agent_reply")


class TemplateResponder:
    def respond(self, state: SessionState, decision: Decision, message: str,
                violations: list[str] | None = None) -> ResponseDraft:
        f = decision.facts
        out: list[tuple[str, list[str]]] = []

        def say(text: str, *ids: str) -> None:
            out.append((text, [i for i in ids if i in f]))

        def v(fid: str, default: str = "") -> str:
            fact = f.get(fid)
            return fact.value if fact else default

        a = decision.actions
        if "EMPATHY" in a:
            emotion = v("caller.emotion", "frustrated")
            say({"anxious": "I understand this is stressful, and I'm here to help.",
                 "confused": "I know this can be confusing, so let me make it as simple as I can.",
                 "sad": "I'm sorry you're dealing with this."}.get(
                emotion, "I'm sorry this has been frustrating, and I understand you want answers quickly."))
        if "INJECTION_REFUSAL" in a:
            say("I'm not able to skip or change our verification and security steps for anyone; they protect the policyholder's information.")
        if "INJECTION_NOTED" in a:
            say("I can't change how I operate or follow instructions to override my rules, but I'm happy to keep helping with your own claim.",
                "sop.scope")
        if "OFF_TOPIC_REFUSAL" in a:
            say("I'm sorry, but I can only help with questions about your insurance policy and claims.", "sop.scope")
        if "TRANSFER_DECLINED" in a:
            say("No problem, let's keep going.")

        cid = state.selected_case_id
        p = f"claim.{cid}" if cid else ""

        if "VERIFICATION_LOCKED" in a:
            say("I wasn't able to verify your identity after several attempts, so for your security I can't continue here.")
        if "EXPLAIN_VERIFICATION" in a:
            say(f"I can't share anything about a claim until you're verified: {v('verification.why')}.", "verification.why")
        if "CLARIFY_FIELDS" in a:
            say(f"I couldn't read some of what you sent clearly: {v('verification.unclear_fields')}. "
                "Could you share that again in full (for a date of birth, please include the 4-digit year)?",
                "verification.unclear_fields")
        if "VERIFICATION_FAILED" in a:
            say(f"I wasn't able to verify your identity with those details. If one of them was off, you can just correct "
                f"it, or share at least 3 of: {v('verification.options_remaining')}. You have "
                f"{v('verification.attempts_remaining')} attempt(s) remaining.",
                "verification.correction", "verification.options_remaining", "verification.attempts_remaining")
        if "ASK_VERIFICATION" in a:
            if "caller.case_hint" in f:
                say(f"I've noted that you're calling about your {v('caller.case_hint')}, and I'll look at it as soon as you're verified.",
                    "caller.case_hint", "sop.after_verification")
            need, have = v("verification.fields_still_needed"), v("verification.fields_received")
            opts = v("verification.options_remaining")
            if "verification.last_attempt" in f and have in ("", "0"):
                say("The details you gave didn't match our records, and for your security I can't say which one. "
                    f"If one was off, you can just correct it, or share any 3 of: {opts}.",
                    "verification.last_attempt", "verification.correction", "verification.options_remaining")
            elif have in ("", "0") and "EXPLAIN_VERIFICATION" in a:
                say(f"You can verify with any 3 of: {opts}.", "verification.options_remaining")
            elif have in ("", "0"):
                say(f"To protect your information, I first need to verify your identity. Please share any 3 of: {opts}.",
                    "verification.options_remaining")
            else:
                say(f"Thanks. I need {need} more detail(s) to verify you: any of {opts}.",
                    "verification.fields_still_needed", "verification.options_remaining")
        if "OFF_TOPIC_REFUSAL" in a and not any(x in a for x in ("ASK_VERIFICATION", "ANSWER_CASE", "OFFER_HUMAN")):
            if "verification.options_remaining" in f:
                say(f"To continue with your claim, please share any 3 of: {v('verification.options_remaining')}.",
                    "verification.options_remaining")
            elif "session.selected_case_id" in f:
                say(f"Is there anything else I can help you with on claim {v('session.selected_case_id')}?", "session.selected_case_id")
        if "VERIFIED" in a:
            if "representative.name" in f:
                say(f"Thank you, {v('representative.name').split()[0]}. I've verified the policyholder's details.",
                    "representative.name", "verification.outcome")
            else:
                say(f"Thank you, {v('policyholder.name')}, you're verified.", "policyholder.name")
        if "REP_NOT_AUTHORIZED" in a:
            say("Thanks. I don't see you listed as an authorized representative on this policy, so I can't share claim details.")
        if "CONSENT_PENDING" in a:
            say(f"Because you're calling on the policyholder's behalf, I've sent {v('consent.method')}. "
                "It's still pending, so please let me know once they've approved it.", "consent.method", "consent.status")
        if "CONSENT_APPROVED" in a:
            say("The policyholder's consent has been approved. Thank you for waiting.", "consent.status")
        if "CONSENT_TIMEOUT" in a:
            say("I haven't received the policyholder's consent in time, so I can't share claim details.", "consent.status")

        if "ASK_INTENT" in a or "NO_MATCHING_CASE" in a or "DISAMBIGUATE" in a:
            ids = state.candidate_case_ids
            listing = "; ".join(
                f"{c} ({v(f'claim.{c}.case_type')}, {v(f'claim.{c}.status')}, created {v(f'claim.{c}.created_at')})" for c in ids)
            cites = [x for c in ids for x in (f"claim.{c}.case_id", f"claim.{c}.case_type", f"claim.{c}.status", f"claim.{c}.created_at")]
            if "NO_MATCHING_CASE" in a:
                say(f"I couldn't find a claim matching \"{v('resolve.no_match_for')}\" on your policy.", "resolve.no_match_for")
            lead = {"ASK_INTENT": "How can I help you today? I see these claims on your policy",
                    "NO_MATCHING_CASE": "Here are the claims I do see",
                    "DISAMBIGUATE": "A few claims could match what you described"}[next(x for x in a if x in ("ASK_INTENT", "NO_MATCHING_CASE", "DISAMBIGUATE"))]
            say(f"{lead}: {listing}. Which one would you like to discuss?", *cites)

        if "NO_CLAIMS_ON_FILE" in a:
            say("I don't see any claims on file for your policy. Is there anything else I can help you with?", "claims.count")
        if "CASE_SELECTED" in a:
            if "session.case_found_from_earlier_hint" in f:
                say(f"Based on what you mentioned earlier, your {v('session.case_found_from_earlier_hint')}, I've pulled up claim {cid}.",
                    "session.case_found_from_earlier_hint", f"{p}.case_id")
            else:
                say(f"I've pulled up claim {cid}.", f"{p}.case_id")
        if "CASE_UNAVAILABLE" in a:
            say("I'm not able to access that claim.")
        if "ANSWER_CASE" in a:
            self._answer_case(state, decision, say, v, p)

        if "OFFER_EMAIL" in a:
            say(f"Before you go, would you like me to email a summary of our conversation, including what we discussed, "
                f"the claim status and next steps, to {v('email.to_masked')}? Just say send or skip.",
                "email.to_masked", "email.summary_contents")
        if "EMAIL_SENT" in a:
            say(f"Done. I've sent the summary to {v('email.sent_to_masked')}. Thank you for calling!", "email.sent_to_masked")
        if "EMAIL_SKIPPED" in a:
            say("No problem, I won't send an email. Thank you for calling, and take care!", "email.status")
        if "OFFER_HUMAN" in a:
            say("Would you like me to connect you with a human representative?", "offer.human_transfer_reason", "sop.human_transfer")
        if "TRANSFER_HUMAN" in a:
            say("I'm connecting you with a human representative now.", "transfer.reason", "transfer.next")
        if "ALREADY_TRANSFERRED" in a:
            say("A human representative will be with you shortly; thank you for your patience.", "transfer.reason")
        if "GOODBYE" in a:
            say("Thanks for calling. If you need anything else about your claims, I'm here to help.")

        reply = " ".join(t for t, _ in out) or "How can I help you with your insurance claim today?"
        return ResponseDraft(rule_check="template", reply=reply,
                             claims=[Claim(text=t, fact_ids=ids) for t, ids in out if ids])

    @staticmethod
    def _answer_case(state: SessionState, decision: Decision, say, v, p: str) -> None:
        f: FactSheet = decision.facts
        cid = state.selected_case_id
        topics = [fid for fid in f.facts if fid.startswith("guide.topic.")]
        alternatives = [fid for fid in f.facts if fid.startswith("guide.alternative.")]
        specific = bool(topics or alternatives)
        overview = "CASE_SELECTED" in decision.actions or not specific
        if overview:
            ctype = v(p + '.case_type')
            say(f"Claim {cid} is {'an' if ctype[:1].lower() in 'aeiou' else 'a'} {ctype} claim created on {v(p + '.created_at')}, and its status is "
                f"{v(p + '.status')}: {v(p + '.summary')}.", f"{p}.case_id", f"{p}.case_type", f"{p}.created_at", f"{p}.status", f"{p}.summary")
            if f"{p}.denial_reason" in f:
                say(f"It was denied because {v(p + '.denial_reason')}.", f"{p}.denial_reason")
            if f"{p}.documents_needed" in f:
                say(f"To reconsider it, the review needs: {v(p + '.documents_needed')}.", f"{p}.documents_needed")
            if f"{p}.appeal_deadline" in f:
                if v(p + ".appeal_deadline_status") == "passed":
                    say(f"The appeal deadline on record was {v(p + '.appeal_deadline')}, which has passed as of today "
                        f"({v('session.today')}).", f"{p}.appeal_deadline", f"{p}.appeal_deadline_status", "session.today")
                    say("Options after a passed appeal deadline are reviewed by a human representative, and I can "
                        "connect you if you'd like.", "sop.passed_deadline_review", "sop.human_transfer")
                else:
                    say(f"The appeal deadline on record is {v(p + '.appeal_deadline')}.", f"{p}.appeal_deadline")
            if "ANSWER_AMOUNTS" in decision.actions and f"{p}.allowed_max_amount" in f:
                say(f"On record for claim {cid}: the amount paid so far (net pay) is ${v(p + '.net_pay')}, the expected "
                    f"reimbursement is ${v(p + '.expected_reimbursement_amount')}, and the maximum allowed amount, "
                    f"which is the most the insurer pays for a covered service rather than a payment, is "
                    f"${v(p + '.allowed_max_amount')}.", f"{p}.net_pay", f"{p}.expected_reimbursement_amount",
                    f"{p}.allowed_max_amount", "schema.allowed_max_amount")
            elif v(p + ".status") in ("closed", "open") and f"{p}.net_pay" in f:
                say(f"The expected reimbursement is ${v(p + '.expected_reimbursement_amount')} and the amount paid so far is "
                    f"${v(p + '.net_pay')}.", f"{p}.expected_reimbursement_amount", f"{p}.net_pay")
        for fid in alternatives:
            say(f.get(fid).value, fid)
        for fid in topics:
            if fid == "guide.topic.missing_required_material_alternatives" and alternatives:
                continue
            say(f.get(fid).value, fid)
        if not specific and "guide.fallback" in f and decision.question and not overview:
            say(f.get("guide.fallback").value, "guide.fallback")
        if "OFFER_HUMAN" not in decision.actions:
            say("Is there anything else I can help you with on this claim?")
