"""Run scenario specs (fixtures/specs/scenarios.json) and score them. Shared by pytest and evals/."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import config
from .grounding.factsheet import FactSheet
from .grounding.gates import check_gates, normalize_quotes
from .grounding.trace_rules import check_trace, claim_access_turn, memory_was_used
from .pipeline import Agent, TurnResult
from .state import SessionState


def load_scenarios() -> list[dict[str, Any]]:
    return json.loads((config.FIXTURES_DIR / "specs" / "scenarios.json").read_text())["scenarios"]


@dataclass
class ScenarioRun:
    spec: dict[str, Any]
    state: SessionState
    results: list[TurnResult]
    failures: list[str] = field(default_factory=list)
    trace_properties: dict[str, bool] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.failures


def run_scenario(agent: Agent, spec: dict[str, Any]) -> ScenarioRun:
    state = SessionState()
    state.consent.scenario = spec.get("consent_scenario", "default")
    agent.start(state)
    results = [agent.handle(state, msg) for msg in spec["turns"]]
    run = ScenarioRun(spec, state, results)
    evaluate(run, agent)
    return run


def evaluate(run: ScenarioRun, agent: Agent) -> None:
    exp, state, results, f = run.spec.get("expect", {}), run.state, run.results, run.failures
    phase_at: dict[int, str] = {}
    current = "VERIFY_ID"
    for turn in range(1, len(results) + 1):
        for e in state.trace:
            if e.turn == turn and e.type == "phase_change":
                current = e.data["to_phase"]
        phase_at[turn] = current

    if "verified_turn" in exp:
        got = next((e.turn for e in state.trace if e.type == "verified"), None)
        if exp["verified_turn"] is None and claim_access_turn(state) is not None:
            f.append(f"expected never verified, got claim access at turn {claim_access_turn(state)}")
        elif exp["verified_turn"] is not None and got != exp["verified_turn"]:
            f.append(f"verified_turn: expected {exp['verified_turn']}, got {got}")
    if "selected_case" in exp and state.selected_case_id != exp["selected_case"]:
        f.append(f"selected_case: expected {exp['selected_case']}, got {state.selected_case_id}")
    if "final_phase" in exp and state.phase.value != exp["final_phase"]:
        f.append(f"final_phase: expected {exp['final_phase']}, got {state.phase.value}")
    if exp.get("memory_used") and not memory_was_used(state):
        f.append("memory_used: case was not resolved from a hint given in an earlier turn")
    if "email" in exp:
        got = state.email.choice and {"send": "sent", "skip": "skipped"}[state.email.choice] or "none"
        if got != exp["email"]:
            f.append(f"email: expected {exp['email']}, got {got}")
    for turn, phase in exp.get("phase_by_turn", {}).items():
        if phase_at.get(int(turn)) != phase:
            f.append(f"turn {turn} phase: expected {phase}, got {phase_at.get(int(turn))}")
    for turn, actions in exp.get("actions_by_turn", {}).items():
        got = results[int(turn) - 1].actions
        missing = [a for a in actions if a not in got]
        if missing:
            f.append(f"turn {turn} actions missing {missing} (got {got})")
    for turn, actions in exp.get("actions_absent_by_turn", {}).items():
        present = [a for a in actions if a in results[int(turn) - 1].actions]
        if present:
            f.append(f"turn {turn} actions must not include {present}")
    # The spec can assert against the runtime gates themselves (one definition of e.g. "prediction"),
    # which is hedge-aware where a substring list is not.
    for turn, prefixes in exp.get("no_gate_violations_by_turn", {}).items():
        res = results[int(turn) - 1]
        facts = FactSheet()
        for f_ in res.facts:
            facts.add(f_["id"], f_["value"], f_["source"])
        hits = [v for v in check_gates(res.reply, facts, state, res.actions) if v.split()[0] in prefixes]
        if hits:
            f.append(f"turn {turn} gate violations: {hits}")
    if "failed_attempts" in exp and state.verification.failed_attempts != exp["failed_attempts"]:
        f.append(f"failed_attempts: expected {exp['failed_attempts']}, got {state.verification.failed_attempts}")
    for turn, pattern in exp.get("reply_matches_by_turn", {}).items():
        if not re.search(pattern, normalize_quotes(results[int(turn) - 1].reply), re.I):
            f.append(f"turn {turn} reply does not match required /{pattern}/")
    for action in exp.get("actions_never", []):
        if any(action in r.actions for r in results):
            f.append(f"action {action} should never occur")
    for turn, words in exp.get("reply_excludes_by_turn", {}).items():
        reply = normalize_quotes(results[int(turn) - 1].reply).casefold()
        bad = [w for w in words if w.casefold() in reply]
        if bad:
            f.append(f"turn {turn} reply contains forbidden {bad}")
    for turn, fact_ids in exp.get("facts_by_turn", {}).items():
        got = {x["id"] for x in results[int(turn) - 1].facts}
        missing = [x for x in fact_ids if x not in got]
        if missing:
            f.append(f"turn {turn} facts missing {missing}")

    report = check_trace(state, agent.repo)
    run.trace_properties = report.properties
    f.extend(f"trace property violated: {v}" for v in report.violations)
