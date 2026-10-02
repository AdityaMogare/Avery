"""FastAPI app: chat endpoints + the built React SPA."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .evaluation import ScenarioRun, evaluate, load_scenarios
from .pipeline import Agent
from .state import PII_FIELDS, SessionState

app = FastAPI(title="SOP-Guided Insurance Claims Agent")
SESSIONS: dict[str, SessionState] = {}
TURN_RESULTS: dict[str, list[Any]] = {}  # per-session TurnResults, so a UI run can be scored like an eval


class EvaluateIn(BaseModel):
    scenario_id: str


class NewSession(BaseModel):
    consent_scenario: str = "default"


class ChatIn(BaseModel):
    session_id: str
    message: str


def _agent(header_key: str | None, header_provider: str | None = None) -> Agent:
    key = (header_key or "").strip()
    # A provider picked in the UI only applies to the key pasted alongside it.
    provider = ((header_provider or "").strip().lower() or None) if key else None
    return Agent(api_key=key or config.env_api_key(), provider=provider)


def snapshot(state: SessionState) -> dict[str, Any]:
    """Debug view of the session. Caller PII values are masked; only field names are exposed."""
    mem = state.memory.model_dump()
    mem["pii"] = {k: {"value": "•••", "turn": v["turn"]} for k, v in mem["pii"].items()}
    return {
        "session_id": state.id,
        "phase": state.phase.value,
        "turn": state.turn,
        "verification": {**state.verification.model_dump(exclude={"failed_signatures"}),
                         "verified_for_claims": state.verified},
        "consent": state.consent.model_dump(),
        "memory": mem,
        "pii_fields_collected": [f for f in PII_FIELDS if f in state.memory.pii],
        "selected_case_id": state.selected_case_id,
        "candidate_case_ids": state.candidate_case_ids,
        "pending_offer": state.pending_offer,
        "counters": state.counters.model_dump(),
        "email": state.email.model_dump(),
        "discussed_topics": state.discussed_topics,
        "transfer_reason": state.transfer_reason,
    }


@app.get("/api/health")
def health() -> dict[str, Any]:
    key = config.env_api_key()
    provider = config.detect_provider(key) if key else None
    return {"ok": True, "provider": provider, "model": config.default_model(provider) if provider else None,
            "server_key_configured": bool(key), "providers": list(config.PROVIDERS)}


@app.post("/api/session")
def new_session(body: NewSession, x_llm_key: str | None = Header(default=None),
                x_llm_provider: str | None = Header(default=None),
                x_openai_key: str | None = Header(default=None)) -> dict[str, Any]:
    state = SessionState()
    state.consent.scenario = body.consent_scenario
    agent = _agent(x_llm_key or x_openai_key, x_llm_provider)
    greeting = agent.start(state)
    SESSIONS[state.id] = state
    TURN_RESULTS[state.id] = []
    return {"session_id": state.id, "reply": greeting, "mode": agent.mode, "state": snapshot(state),
            "events": [e.model_dump() for e in state.trace]}


@app.post("/api/chat")
def chat(body: ChatIn, x_llm_key: str | None = Header(default=None), x_llm_provider: str | None = Header(default=None),
         x_openai_key: str | None = Header(default=None)) -> dict[str, Any]:
    state = SESSIONS.get(body.session_id)
    if not state:
        raise HTTPException(404, "unknown session")
    if not body.message.strip():
        raise HTTPException(400, "empty message")
    result = _agent(x_llm_key or x_openai_key, x_llm_provider).handle(state, body.message.strip()[:2000])
    TURN_RESULTS.setdefault(state.id, []).append(result)
    return {**result.__dict__, "state": snapshot(state)}


@app.get("/api/scenarios")
def scenarios() -> dict[str, Any]:
    """The executable conversation specs (fixtures/specs/scenarios.json) for the UI's test-case browser."""
    return {"scenarios": load_scenarios()}


@app.post("/api/session/{session_id}/evaluate")
def evaluate_session(session_id: str, body: EvaluateIn) -> dict[str, Any]:
    """Score a session that ran a scenario's turns against that scenario's expectations + trace properties."""
    state = SESSIONS.get(session_id)
    spec = next((s for s in load_scenarios() if s["id"] == body.scenario_id), None)
    if not state or not spec:
        raise HTTPException(404, "unknown session or scenario")
    results = TURN_RESULTS.get(session_id, [])
    if len(results) < len(spec["turns"]):
        raise HTTPException(400, f"session has {len(results)} turns; scenario needs {len(spec['turns'])}")
    run = ScenarioRun(spec, state, results)
    evaluate(run, Agent(api_key=None))
    return {"scenario_id": spec["id"], "passed": run.passed, "failures": run.failures,
            "trace_properties": run.trace_properties}


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    state = SESSIONS.get(session_id)
    if not state:
        raise HTTPException(404, "unknown session")
    return {"state": snapshot(state), "transcript": [m.model_dump() for m in state.transcript],
            "trace": [e.model_dump() for e in state.trace]}


if config.FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (config.FRONTEND_DIST / path).resolve()
        if path and candidate.is_relative_to(config.FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(config.FRONTEND_DIST / "index.html")
