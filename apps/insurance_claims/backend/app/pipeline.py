"""TurnPipeline: understand -> merge memory -> SOP controller -> tools/FactSheet -> respond -> verify."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config
from .fixtures import Repository, get_repo
from .grounding.judge import judge_reply
from .grounding.verifier import verify_reply
from .llm import LLMClient, LLMError
from .responder import LLMResponder, ResponseDraft, TemplateResponder
from .sop.controller import SOPController
from .state import Message, SessionState
from .understanding import HeuristicUnderstander, LLMUnderstander

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
    def __init__(self, api_key: str | None = None, repo: Repository | None = None, model: str | None = None):
        self.repo = repo or get_repo()
        self.controller = SOPController(self.repo)
        self.template = TemplateResponder()
        self.heuristic = HeuristicUnderstander()
        self.llm = LLMClient(api_key, model) if api_key else None
        self.mode = f"llm:{self.llm.model}" if self.llm else "offline"

    def start(self, state: SessionState) -> str:
        state.transcript.append(Message(role="assistant", content=GREETING, turn=0))
        state.log("session_started", mode=self.mode, consent_scenario=state.consent.scenario)
        return GREETING

    def handle(self, state: SessionState, message: str) -> TurnResult:
        state.turn += 1
        first_event = len(state.trace)
        errors: list[str] = []
        state.transcript.append(Message(role="user", content=message, turn=state.turn))

        # 1. Understand (LLM extraction; heuristic offline / on error)
        understanding, source = None, "heuristic"
        if self.llm:
            try:
                understanding, source = LLMUnderstander(self.llm).understand(state, message), "llm"
            except LLMError as exc:
                errors.append(f"understanding: {exc}")
        if understanding is None:
            understanding = self.heuristic.understand(state, message)
        state.log("understanding", source=source,
                  signals=understanding.model_dump(exclude_none=True, exclude_defaults=True,
                                                   exclude={"full_name", "dob", "phone", "email", "id_last4"}),
                  pii_fields=[k for k in ("full_name", "dob", "phone", "email", "id_last4") if getattr(understanding, k)])

        # 2-4. Deterministic SOP step (memory, gates, tools, facts)
        decision = self.controller.step(state, understanding, message)
        state.log("decision", phase=state.phase.value, actions=decision.actions, fact_ids=list(decision.facts.facts))

        # 5-6. Respond, verify, regenerate once, fall back to the deterministic template
        draft, check, responder_used = self._respond_verified(state, decision, message, errors)

        judge = None
        if self.llm and config.LIVE_JUDGE:
            try:
                judge_result = judge_reply(self.llm, draft.reply, decision.facts, message)
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
                check = verify_reply(draft.reply, [c.model_dump() for c in draft.claims], decision.facts, state, self.repo)
                if check.ok:
                    return draft, check, "llm" if attempt == 0 else "llm_regenerated"
                violations = check.violations
                state.log("grounding_violation", attempt=attempt + 1, violations=check.violations, draft=draft.reply)
        draft = self.template.respond(state, decision, message)
        check = verify_reply(draft.reply, [c.model_dump() for c in draft.claims], decision.facts, state, self.repo)
        used = "template" if not self.llm else "template_fallback"
        if self.llm:
            state.log("fallback", reason="LLM reply failed grounding twice or LLM unavailable")
        return draft, check, used
