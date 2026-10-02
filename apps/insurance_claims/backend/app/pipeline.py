"""TurnPipeline: understand -> merge memory -> SOP controller -> tools/FactSheet -> respond -> verify."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config
from .fixtures import Repository, get_repo
from .grounding.extraction_guard import ground_understanding
from .grounding.judge import judge_reply
from .grounding.verifier import verify_reply
from .llm import LLMClient, LLMError
from .responder import LLMResponder, ResponseDraft, TemplateResponder
from .sop.controller import SOPController
from .state import Message, SessionState
from .text_normalize import normalize_spoken
from .understanding import HeuristicUnderstander, LLMUnderstander, high_precision_flags

GREETING = ("Hi, thanks for calling claims support. I'm Avery. Before I can look into any claim, I need to "
            "verify your identity. Please share any 3 of: your full name, date of birth, phone number, "
            "email address, or the last 4 digits of your SSN or national ID. How can I help today?")


@dataclass
class TurnResult:
    reply: str
    citations: list[dict[str, Any]]
    actions: list[str]
    verifier: dict[str, Any]
    facts: list[dict[str, str]]
    events: list[dict[str, Any]]
    mode: str
    judge: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, api_key: str | None = None, repo: Repository | None = None, model: str | None = None,
                 provider: str | None = None):
        self.repo = repo or get_repo()
        self.controller = SOPController(self.repo)
        self.template = TemplateResponder()
        self.heuristic = HeuristicUnderstander()
        self.llm = LLMClient(api_key, model, provider) if api_key else None
        judge_model = config.LLM_JUDGE_MODEL
        self.judge_llm = (LLMClient(api_key, judge_model, self.llm.provider)
                          if self.llm and judge_model and judge_model != self.llm.model else self.llm)
        self.mode = f"llm:{self.llm.provider}:{self.llm.model}" if self.llm else "offline"

    def start(self, state: SessionState) -> str:
        state.transcript.append(Message(role="assistant", content=GREETING, turn=0))
        state.log("session_started", mode=self.mode, consent_scenario=state.consent.scenario)
        return GREETING

    def handle(self, state: SessionState, message: str) -> TurnResult:
        state.turn += 1
        first_event = len(state.trace)
        errors: list[str] = []
        state.transcript.append(Message(role="user", content=message, turn=state.turn))
        # Spoken values ("four four seven two") in written form, for the regex extractor and the input
        # guard. The model and the transcript keep the caller's raw words.
        written = normalize_spoken(message)
        if written != message:
            state.log("spoken_normalized")

        # 1. Understand (LLM extraction; heuristic offline / on error)
        understanding, source = None, "heuristic"
        if self.llm:
            try:
                understanding, source = LLMUnderstander(self.llm).understand(state, message), "llm"
            except LLMError as exc:
                errors.append(f"understanding: {exc}")
        if understanding is None:
            understanding = self.heuristic.understand(state, written)
        state.log("understanding", source=source,
                  signals=understanding.model_dump(exclude_none=True, exclude_defaults=True,
                                                   exclude={"full_name", "dob", "phone", "email", "id_last4"}),
                  pii_fields=[k for k in ("full_name", "dob", "phone", "email", "id_last4") if getattr(understanding, k)])

        # 1a. Deterministic backfill: small models drop format-rigid values (live: nano omitted a DOB and SSN
        #     digits that were in the message). Regex extraction reads the raw text, so it is grounded by
        #     construction; it only fills fields the model left empty.
        if source == "llm":
            regex = self.heuristic.understand(state, written)
            filled = {}
            for attr in ("dob", "phone", "email", "id_last4", "policy_number", "case_id", "full_name",
                         "case_type", "case_status", "case_month"):
                if getattr(understanding, attr) is None and getattr(regex, attr) is not None:
                    setattr(understanding, attr, getattr(regex, attr))
                    filled[attr] = "<redacted>" if attr in ("dob", "phone", "email", "id_last4") else getattr(regex, attr)
            if filled:
                state.log("extraction_backfill", fields=filled)
            # Safety flags are OR-ed with high-precision deterministic detectors (defense in depth: a model
            # miss must not reopen a gate). Only keyword-level detectors are used, not the broad heuristics.
            injection, off_topic = high_precision_flags(written)
            if (injection and not understanding.is_injection_attempt) or (off_topic and not understanding.is_off_topic):
                state.log("guardrail_backstop", injection=injection, off_topic=off_topic)
            understanding.is_injection_attempt |= injection
            understanding.is_off_topic |= off_topic
            # Follow-up topics and "I don't have the document" use precise phrase detectors as a backstop too.
            for topic in regex.followup_topics:
                if topic not in understanding.followup_topics:
                    understanding.followup_topics.append(topic)
            understanding.lacks_document |= regex.lacks_document
            understanding.cannot_obtain_alternatives |= regex.cannot_obtain_alternatives

        # 1b. Input grounding: drop extracted values the caller never actually said.
        guard = ground_understanding(understanding, written)
        if guard.rejected or guard.corrected:
            state.log("extraction_guard", rejected=sorted(guard.rejected), corrected=sorted(guard.corrected))
        understanding = guard.understanding

        # 2-4. Deterministic SOP step (memory, gates, tools, facts)
        decision = self.controller.step(state, understanding, message, rejected=guard.rejected)
        state.log("decision", phase=state.phase.value, actions=decision.actions, fact_ids=list(decision.facts.facts))

        # 5-6. Respond, verify, regenerate once, fall back to the deterministic template
        draft, check, responder_used = self._respond_verified(state, decision, message, errors)

        judge = None
        if self.llm and config.LIVE_JUDGE:
            try:
                judge_result = judge_reply(self.judge_llm, draft.reply, decision.facts, message)
                judge = {"faithfulness": judge_result.faithfulness, **judge_result.model_dump()}
            except LLMError as exc:
                errors.append(f"judge: {exc}")

        citations = [c.model_dump() | {"facts": [decision.facts.get(i).value for i in c.fact_ids if i in decision.facts]}
                     for c in draft.claims]
        state.transcript.append(Message(role="assistant", content=draft.reply, turn=state.turn, citations=citations))
        state.log("response", responder=responder_used, verifier_ok=check.ok, violations=check.violations,
                  cited_fact_ids=sorted({i for c in draft.claims for i in c.fact_ids}),
                  claim_data_in_facts=decision.facts.has_claim_data(), verified=state.verified)
        return TurnResult(
            reply=draft.reply, citations=citations, actions=decision.actions, verifier=check.as_dict(),
            facts=decision.facts.as_list(), events=[e.model_dump() for e in state.trace[first_event:]],
            mode=self.mode, judge=judge, errors=errors,
        )

    def _respond_verified(self, state, decision, message, errors) -> tuple[ResponseDraft, Any, str]:
        if self.llm:
            responder = LLMResponder(self.llm)
            violations: list[str] | None = None
            for attempt in range(2):
                try:
                    draft = responder.respond(state, decision, message, violations)
                except LLMError as exc:
                    errors.append(f"responder: {exc}")
                    break
                check = verify_reply(draft.reply, [c.model_dump() for c in draft.claims], decision.facts, state, self.repo,
                                     decision.actions)
                if check.ok:
                    return draft, check, "llm" if attempt == 0 else "llm_regenerated"
                violations = check.violations
                state.log("grounding_violation", attempt=attempt + 1, violations=check.violations, draft=draft.reply)
        draft = self.template.respond(state, decision, message)
        check = verify_reply(draft.reply, [c.model_dump() for c in draft.claims], decision.facts, state, self.repo,
                                     decision.actions)
        used = "template" if not self.llm else "template_fallback"
        if self.llm:
            state.log("fallback", reason="LLM reply failed grounding twice or LLM unavailable")
        return draft, check, used
