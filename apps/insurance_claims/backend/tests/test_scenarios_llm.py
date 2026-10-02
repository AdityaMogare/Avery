"""Live-model runs of the same specs plus the LLM groundedness judge. Skipped without OPENAI_API_KEY.

Run: OPENAI_API_KEY=... pytest -m llm
"""

import pytest

from app.evaluation import load_scenarios, run_scenario
from app.grounding.factsheet import FactSheet
from app.grounding.judge import judge_reply

SCENARIOS = load_scenarios()
pytestmark = pytest.mark.llm


@pytest.mark.parametrize("spec", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario_live(live_agent, spec):
    run = run_scenario(live_agent, spec)
    transcript = "\n".join(f"{m.role}: {m.content}" for m in run.state.transcript)
    assert run.passed, "\n".join(run.failures) + "\n\n" + transcript


def test_live_replies_judged_faithful(live_agent):
    spec = next(s for s in SCENARIOS if s["id"] == "grounded_followups")
    run = run_scenario(live_agent, spec)
    for turn, result in enumerate(run.results, 1):
        facts = FactSheet()
        for f in result.facts:
            facts.add(f["id"], f["value"], f["source"])
        convo = "\n".join(f"{m.role.upper()}: {m.content}" for m in run.state.transcript
                          if m.turn < turn or (m.turn == turn and m.role == "user"))
        verdict = judge_reply(live_agent.judge_llm, result.reply, facts, spec["turns"][turn - 1], convo)
        unsupported = [c for c in verdict.factual if c.verdict != "supported"]
        assert not unsupported, f"turn {turn}: {[(c.claim, c.reason) for c in unsupported]}"


def test_judge_flags_planted_hallucination(live_agent):
    facts = FactSheet()
    facts.add("claim.CL-2048.status", "denied", "claim_record")
    facts.add("guide.average_processing_time", "usually less than a week", "guideline")
    verdict = judge_reply(live_agent.judge_llm, "Your claim was denied, and appeals are always approved within 48 hours.",
                          facts, "What happens next?")
    assert any(c.verdict in ("unsupported", "contradicted") for c in verdict.claims)
