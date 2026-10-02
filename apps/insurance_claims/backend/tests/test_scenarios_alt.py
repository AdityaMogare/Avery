"""The same SOP harness on data it was never tuned on (fixtures_alt): new people, claims, documents,
deadlines and a representative. Guards against logic that only works for the sample fixtures."""

import pytest

from app import config
from app.evaluation import load_scenarios, run_scenario
from app.fixtures import Repository
from app.pipeline import Agent

ALT_DIR = config.PROJECT_DIR / "fixtures_alt"
SCENARIOS = load_scenarios(ALT_DIR)


@pytest.fixture(scope="module")
def alt_agent():
    return Agent(api_key=None, repo=Repository(ALT_DIR))


@pytest.mark.parametrize("spec", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_alt_scenario_offline(alt_agent, spec):
    run = run_scenario(alt_agent, spec)
    transcript = "\n".join(f"{m.role}: {m.content}" for m in run.state.transcript)
    assert run.passed, "\n".join(run.failures) + "\n\n" + transcript


def test_alt_data_is_disjoint_from_sample_data(repo):
    alt = Repository(ALT_DIR)
    assert not {p["party_id"] for p in alt.policyholders} & {p["party_id"] for p in repo.policyholders}
    assert not {c["case_id"] for c in alt.claims} & {c["case_id"] for c in repo.claims}
