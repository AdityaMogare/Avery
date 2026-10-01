"""Every scenario spec, run end-to-end with the deterministic offline understander + template responder.

This proves the SOP harness (gates, memory, tool selection, grounding, trace properties) independently
of model behaviour. The same specs run against the live model in test_scenarios_llm.py.
"""

import pytest

from app.evaluation import load_scenarios, run_scenario

SCENARIOS = load_scenarios()


@pytest.mark.parametrize("spec", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario_offline(offline_agent, spec):
    run = run_scenario(offline_agent, spec)
    transcript = "\n".join(f"{m.role}: {m.content}" for m in run.state.transcript)
    assert run.passed, "\n".join(run.failures) + "\n\n" + transcript


def test_memory_hint_is_stored_during_verify_id(offline_agent):
    from app.state import SessionState

    s = SessionState()
    offline_agent.start(s)
    offline_agent.handle(s, "I'm calling about my denied healthcare claim from January.")
    assert s.phase.value == "VERIFY_ID"
    hints = {k: v.value for k, v in s.memory.case_hints.items()}
    assert hints == {"status": "denied", "case_type": "healthcare", "month": 1}
    assert all(v.turn == 1 for v in s.memory.case_hints.values())


def test_email_summary_is_grounded_in_claim_record(offline_agent, repo):
    from app.state import SessionState

    s = SessionState()
    offline_agent.start(s)
    for m in ["My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472. Calling about my denied healthcare claim.",
              "That's all."]:
        offline_agent.handle(s, m)
    preview = s.email.preview
    claim = repo.claim("CL-2048")
    assert preview["claim"]["status"] == claim["status"]
    assert preview["claim"]["denial_reason"] == claim["denial_reason"]
    assert any("pathology report" in step for step in preview["next_steps"])
    assert s.email.choice is None  # nothing sent until the caller chooses
