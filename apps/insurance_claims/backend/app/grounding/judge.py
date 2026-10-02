"""LLM groundedness judge: enumerate atomic claims first, then verify each against the facts.

Used by the eval suite (and optionally live via LIVE_JUDGE=true). It complements the deterministic
verifier by catching paraphrased or qualitative claims that regexes cannot (e.g. invented procedures).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .factsheet import FactSheet

JUDGE_SYSTEM = """You audit an insurance customer-service agent's reply for groundedness.

Step 1: list every atomic factual claim in the reply (statements about the caller's claims, amounts,
dates, documents, deadlines, timelines, procedures, policies or outcomes). Ignore empathy, greetings,
questions to the caller, and statements about what the agent will do next in this conversation.
Do not list non-factual statements at all. If you are unsure whether something is factual, list it with
verdict "not_factual".
Step 2: for each claim decide:
- supported: entailed by the FACTS (paraphrase is fine) or a restatement of something the caller said
  anywhere in the CONVERSATION (e.g. "your mother" if the caller said "my mother").
- unsupported: not entailed by FACTS (invented, embellished, or more specific than FACTS).
- contradicted: conflicts with FACTS.
Be strict: adding an unstated number, timeline, rule or promise makes a claim unsupported."""


class JudgedClaim(BaseModel):
    claim: str
    verdict: Literal["supported", "unsupported", "contradicted", "not_factual"]
    fact_ids: list[str] = Field(default_factory=list)
    reason: str


class JudgeResult(BaseModel):
    claims: list[JudgedClaim] = Field(default_factory=list)

    @property
    def faithfulness(self) -> float:
        factual = self.factual
        if not factual:
            return 1.0
        return sum(c.verdict == "supported" for c in factual) / len(factual)

    @property
    def factual(self) -> list["JudgedClaim"]:
        return [c for c in self.claims if c.verdict != "not_factual"]


def judge_reply(llm, reply: str, facts: FactSheet, caller_message: str, conversation: str = "") -> JudgeResult:
    user = (f"FACTS:\n{facts.render()}\n\nCONVERSATION SO FAR:\n{conversation or '(not provided)'}\n\n"
            f"CALLER'S LATEST MESSAGE: {caller_message}\n\nAGENT REPLY TO JUDGE: {reply}")
    return llm.structured(JUDGE_SYSTEM, [{"role": "user", "content": user}], JudgeResult, "groundedness_judgement")
