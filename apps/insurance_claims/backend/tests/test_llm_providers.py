"""Provider-agnostic LLMClient: key-prefix detection and each provider branch, with the SDK clients faked."""

import json
from types import SimpleNamespace

import pytest

from app import config
from app.llm import LLMClient, LLMError
from app.pipeline import Agent
from app.responder import ResponseDraft

REPLY = {"reply": "Hello.", "claims": []}


@pytest.mark.parametrize("key,expected", [
    ("sk-proj-abc", "openai"),
    ("sk-abc", "openai"),
    ("sk-ant-api03-abc", "anthropic"),
    ("AIzaSyabc", "gemini"),
    ("sk-or-v1-abc", "openrouter"),
    ("gsk_abc", "groq"),
    ("xai-abc", "xai"),
    ("no-known-prefix", "openai"),
])
def test_detect_provider_from_key_prefix(key, expected, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", None)
    assert config.detect_provider(key) == expected


def test_explicit_provider_overrides_prefix(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", None)
    assert config.detect_provider("sk-abc", "openrouter") == "openrouter"
    assert config.detect_provider("sk-abc", "bogus") == "openai"


class FakeChat:
    """OpenAI-compatible chat.completions; optionally rejects json_schema like some third-party endpoints."""

    def __init__(self, reject_schema=False):
        self.reject_schema = reject_schema
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if self.reject_schema and kw["response_format"]["type"] == "json_schema":
            err = RuntimeError("response_format json_schema is not supported for this model")
            err.status_code = 400
            raise err
        msg = SimpleNamespace(content="```json\n" + json.dumps(REPLY) + "\n```")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def openai_client(provider, chat, monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", None)
    client = LLMClient("key", provider=provider)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    return client


def test_openai_compatible_branch_uses_strict_schema(monkeypatch):
    chat = FakeChat()
    client = openai_client("gemini", chat, monkeypatch)
    assert client.model == config.PROVIDERS["gemini"]["model"]
    assert client.structured("sys", [{"role": "user", "content": "hi"}], ResponseDraft, "draft").reply == "Hello."
    assert chat.calls[0]["response_format"]["type"] == "json_schema"
    assert "reasoning_effort" not in chat.calls[0]


def test_json_object_fallback_when_schema_rejected(monkeypatch):
    chat = FakeChat(reject_schema=True)
    client = openai_client("groq", chat, monkeypatch)
    assert client.structured("sys", [], ResponseDraft, "draft").reply == "Hello."
    assert [c["response_format"]["type"] for c in chat.calls] == ["json_schema", "json_object"]
    assert "JSON Schema" in chat.calls[1]["messages"][0]["content"]
    client.structured("sys", [], ResponseDraft, "draft")  # remembered: no second json_schema attempt
    assert [c["response_format"]["type"] for c in chat.calls[2:]] == ["json_object"]


def test_auth_error_is_not_retried_as_json_object(monkeypatch):
    class Unauthorized(FakeChat):
        def create(self, **kw):
            self.calls.append(kw)
            err = RuntimeError("invalid api key")
            err.status_code = 401
            raise err

    chat = Unauthorized()
    client = openai_client("openai", chat, monkeypatch)
    with pytest.raises(LLMError, match="openai"):
        client.structured("sys", [], ResponseDraft, "draft")
    assert len(chat.calls) == 1


def test_anthropic_branch(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", None)
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=json.dumps(REPLY))])

    client = LLMClient("sk-ant-abc")
    client.client = SimpleNamespace(messages=SimpleNamespace(create=create))
    assert client.provider == "anthropic" and client.model == "claude-opus-5-5"
    assert client.structured("sys", [{"role": "user", "content": "hi"}], ResponseDraft, "draft").reply == "Hello."
    assert calls[0]["system"] == "sys"
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_agent_mode_names_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", None)
    monkeypatch.setattr(config, "LLM_JUDGE_MODEL", None)
    assert Agent(api_key="sk-ant-abc").mode == "llm:anthropic:claude-opus-5-5"
