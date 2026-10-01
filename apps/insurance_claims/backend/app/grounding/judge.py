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
Step 2: for each claim decide:
- supported: entailed by the FACTS (paraphrase is fine) or a restatement of what the caller said.
- unsupported: not entailed by FACTS (invented, embellished, or more specific than FACTS).
- contradicted: conflicts with FACTS.
Be strict: adding an unstated number, timeline, rule or promise makes a claim unsupported."""


class JudgedClaim(BaseModel):
    claim: str
    verdict: Literal["supported", "unsupported", "contradicted"]
    fact_ids: list[str] = Field(default_factory=list)
    reason: str


class JudgeResult(BaseModel):
    claims: list[JudgedClaim] = Field(default_factory=list)

    @property
    def faithfulness(self) -> float:
        if not self.claims:
            return 1.0
        return sum(c.verdict == "supported" for c in self.claims) / len(self.claims)


def judge_reply(llm, reply: str, facts: FactSheet, caller_message: str) -> JudgeResult:
    user = f"FACTS:\n{facts.render()}\n\nCALLER SAID: {caller_message}\n\nAGENT REPLY: {reply}"
    return llm.structured(JUDGE_SYSTEM, [{"role": "user", "content": user}], JudgeResult, "groundedness_judgement")
