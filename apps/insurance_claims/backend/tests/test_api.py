"""API smoke tests for the scenario browser endpoints (offline mode)."""

from fastapi.testclient import TestClient

from app import api

client = TestClient(api.app)


def test_list_scenarios():  # no model call involved
    data = client.get("/api/scenarios").json()["scenarios"]
    assert len(data) >= 31 and any(s.get("category") == "edge_case" for s in data)


def test_run_and_evaluate_scenario_through_api(monkeypatch):
    monkeypatch.setattr(api.config, "env_api_key", lambda: None)
    spec = next(s for s in client.get("/api/scenarios").json()["scenarios"] if s["id"] == "margaret_demo_single_utterance")
    sid = client.post("/api/session", json={"consent_scenario": spec.get("consent_scenario", "default")}).json()["session_id"]
    for turn in spec["turns"]:
        assert client.post("/api/chat", json={"session_id": sid, "message": turn}).status_code == 200
    res = client.post(f"/api/session/{sid}/evaluate", json={"scenario_id": spec["id"]}).json()
    assert res["passed"], res["failures"]


def test_evaluate_rejects_incomplete_run(monkeypatch):
    monkeypatch.setattr(api.config, "env_api_key", lambda: None)
    sid = client.post("/api/session", json={}).json()["session_id"]
    r = client.post(f"/api/session/{sid}/evaluate", json={"scenario_id": "margaret_demo_single_utterance"})
    assert r.status_code == 400
