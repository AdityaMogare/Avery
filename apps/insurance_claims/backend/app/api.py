"""FastAPI app: chat endpoints + the built React SPA."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .pipeline import Agent
from .state import PII_FIELDS, SessionState

app = FastAPI(title="SOP-Guided Insurance Claims Agent")
SESSIONS: dict[str, SessionState] = {}


class NewSession(BaseModel):
    consent_scenario: str = "default"


class ChatIn(BaseModel):
    session_id: str
    message: str


def _agent(header_key: str | None) -> Agent:
    return Agent(api_key=(header_key or "").strip() or config.env_api_key())


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
    return {"ok": True, "model": config.OPENAI_MODEL, "server_key_configured": bool(config.env_api_key())}


@app.post("/api/session")
def new_session(body: NewSession, x_openai_key: str | None = Header(default=None)) -> dict[str, Any]:
    state = SessionState()
    state.consent.scenario = body.consent_scenario
    agent = _agent(x_openai_key)
    greeting = agent.start(state)
    SESSIONS[state.id] = state
    return {"session_id": state.id, "reply": greeting, "mode": agent.mode, "state": snapshot(state),
            "events": [e.model_dump() for e in state.trace]}


@app.post("/api/chat")
def chat(body: ChatIn, x_openai_key: str | None = Header(default=None)) -> dict[str, Any]:
    state = SESSIONS.get(body.session_id)
    if not state:
        raise HTTPException(404, "unknown session")
    if not body.message.strip():
        raise HTTPException(400, "empty message")
    result = _agent(x_openai_key).handle(state, body.message.strip()[:2000])
    return {**result.__dict__, "state": snapshot(state)}


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
