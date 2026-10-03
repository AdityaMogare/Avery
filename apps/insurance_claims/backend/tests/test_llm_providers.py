"""Provider-agnostic LLMClient: key-prefix detection, model fallback chains and overrides, with the SDK faked."""

import json
from types import SimpleNamespace

import pytest

from app import api, config, llm
from app.llm import LLMClient, LLMError
from app.pipeline import Agent
from app.responder import ResponseDraft

REPLY = {"reply": "Hello.", "claims": []}


@pytest.mark.parametrize("key,expected", [
    ("sk-proj-abc", "openai"),
    ("sk-abc", "openai"),
    ("AIzaSyabc", "gemini"),
    ("sk-or-v1-abc", "openrouter"),
    ("no-known-prefix", "openai"),
])
def test_detect_provider_from_key_prefix(key, expected, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", None)
    assert config.detect_provider(key) == expected


def test_explicit_provider_overrides_prefix(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", None)
    assert config.detect_provider("sk-abc", "openrouter") == "openrouter"
    assert config.detect_provider("sk-abc", "bogus") == "openai"


@pytest.mark.parametrize("key,name", [("sk-ant-api03-abc", "Anthropic"), ("gsk_abc", "Groq"), ("xai-abc", "xAI")])
def test_unsupported_provider_key_gets_clear_notice(key, name, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", None)
    with pytest.raises(config.UnsupportedKeyError, match=f"{name} keys aren't supported"):
        config.detect_provider(key)
    agent = Agent(api_key=key)  # degrades to offline with the notice, instead of an OpenAI 401 every turn
    assert agent.llm is None and agent.mode == "offline" and "OpenRouter" in agent.notice


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


@pytest.fixture(autouse=True)
def clean_model_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", None)
    monkeypatch.setattr(config, "LLM_MODEL", None)
    monkeypatch.setattr(config, "LLM_JUDGE_MODEL", None)
    monkeypatch.setattr(config, "PROVIDER_MODELS", {name: None for name in config.PROVIDERS})
    monkeypatch.setattr(llm, "_RESOLVED_MODEL", {})


def openai_client(provider, chat, monkeypatch, key="key", model=None):
    client = LLMClient(key, model=model, provider=provider)
    client.client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    return client


def test_openai_compatible_branch_uses_strict_schema(monkeypatch):
    chat = FakeChat()
    client = openai_client("gemini", chat, monkeypatch)
    assert client.model == config.PROVIDERS["gemini"]["models"][0]
    assert client.structured("sys", [{"role": "user", "content": "hi"}], ResponseDraft, "draft").reply == "Hello."
    assert chat.calls[0]["response_format"]["type"] == "json_schema"
    assert "reasoning_effort" not in chat.calls[0]


def test_json_object_fallback_when_schema_rejected(monkeypatch):
    chat = FakeChat(reject_schema=True)
    client = openai_client("openrouter", chat, monkeypatch)
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


class RetiredModel(FakeChat):
    """Rejects some model ids with the 404 Gemini returned for gemini-2.5-flash."""

    def __init__(self, retired):
        super().__init__()
        self.retired = set(retired)

    def create(self, **kw):
        if kw["model"] in self.retired:
            self.calls.append(kw)
            err = RuntimeError(f"Error code: 404 - models/{kw['model']} is no longer available to new users")
            err.status_code = 404
            raise err
        return super().create(**kw)


def test_retired_model_falls_back_to_next_in_chain(monkeypatch):
    first, second = config.PROVIDERS["gemini"]["models"][:2]
    chat = RetiredModel({first})
    client = openai_client("gemini", chat, monkeypatch, key="AIza-test")
    assert client.structured("sys", [], ResponseDraft, "draft").reply == "Hello."
    assert [c["model"] for c in chat.calls] == [first, second]
    assert client.model == second and client.fallbacks == [{"from": first, "to": second, "reason": "unavailable"}]
    # A fresh client for the same key (the API builds one per request) starts on the working model.
    again = openai_client("gemini", chat, monkeypatch, key="AIza-test")
    assert again.model == second
    # A different key does not inherit it.
    assert openai_client("gemini", chat, monkeypatch, key="AIza-other").model == first


def test_every_model_unavailable_is_fatal_and_short(monkeypatch):
    chat = RetiredModel(config.PROVIDERS["openrouter"]["models"])
    client = openai_client("openrouter", chat, monkeypatch)
    with pytest.raises(LLMError, match="no model available to this key") as info:
        client.structured("sys", [], ResponseDraft, "draft")
    assert info.value.fatal
    assert len(chat.calls) == len(config.PROVIDERS["openrouter"]["models"])


def test_ui_model_override_tried_first_then_defaults(monkeypatch):
    chat = RetiredModel({"bogus-model"})
    client = openai_client("openai", chat, monkeypatch, model="bogus-model")
    assert client.models[0] == "bogus-model"
    client.structured("sys", [], ResponseDraft, "draft")
    assert client.model == config.PROVIDERS["openai"]["models"][0]


def test_server_model_override_does_not_leak_to_other_providers(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(config, "env_api_key", lambda: "sk-server")
    assert config.default_model("openai") == "gpt-5.4-mini"
    assert config.default_model("gemini") == config.PROVIDERS["gemini"]["models"][0]
    monkeypatch.setattr(config, "PROVIDER_MODELS", {**config.PROVIDER_MODELS, "gemini": "gemini-3.5-flash-lite"})
    assert config.default_model("gemini") == "gemini-3.5-flash-lite"


def test_api_passes_ui_model_only_with_a_pasted_key(monkeypatch):
    monkeypatch.setattr(config, "env_api_key", lambda: None)
    assert api._agent("AIza-x", None, "gemini-3.5-flash-lite").mode == "llm:gemini:gemini-3.5-flash-lite"
    assert api._agent(None, None, "gemini-3.5-flash-lite").mode == "offline"


def test_fatal_error_skips_remaining_llm_calls_and_logs_fallback(monkeypatch):
    from app.state import SessionState

    class Unauthorized(FakeChat):
        def create(self, **kw):
            self.calls.append(kw)
            err = RuntimeError("invalid api key")
            err.status_code = 401
            raise err

    agent = Agent(api_key="sk-x")
    chat = Unauthorized()
    agent.llm.client = SimpleNamespace(chat=SimpleNamespace(completions=chat))
    result = agent.handle(SessionState(), "Hi, I'm Margaret Chen.")
    assert len(chat.calls) == 1  # understanding failed fatally; the responder did not retry the bad key
    assert result.errors == ["understanding: openai rejected the API key (401): invalid api key"]
    assert result.reply  # verified template still answers


def test_agent_mode_reports_model_after_fallback(monkeypatch):
    from app.state import SessionState

    first, second = config.PROVIDERS["gemini"]["models"][:2]
    agent = Agent(api_key="AIza-y")
    assert agent.mode == f"llm:gemini:{first}"
    agent.llm.client = SimpleNamespace(chat=SimpleNamespace(completions=RetiredModel({first})))
    result = agent.handle(SessionState(), "Hi")
    assert result.mode == f"llm:gemini:{second}"
    assert any(e["type"] == "model_fallback" and e["data"] == {"provider": "gemini", "from": first, "to": second,
                                                                  "reason": "unavailable"}
               for e in result.events)


GEMINI_DAILY_429 = ("Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota', "
                    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'violations': [{'quotaId': "
                    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}]")


class Status(FakeChat):
    """Returns the given (status, message) error for listed models; others succeed."""

    def __init__(self, errors):
        super().__init__()
        self.errors = errors

    def create(self, **kw):
        if kw["model"] in self.errors:
            self.calls.append(kw)
            status, message = self.errors[kw["model"]]
            err = RuntimeError(message)
            err.status_code = status
            raise err
        return super().create(**kw)


def test_daily_quota_moves_to_next_model(monkeypatch):
    first, second = config.PROVIDERS["gemini"]["models"][:2]
    chat = Status({first: (429, GEMINI_DAILY_429)})
    client = openai_client("gemini", chat, monkeypatch, key="AIza-quota")
    assert client.structured("sys", [], ResponseDraft, "draft").reply == "Hello."
    assert client.model == second
    assert client.fallbacks == [{"from": first, "to": second, "reason": "daily_quota"}]


def test_daily_quota_on_every_model_is_one_short_fatal_message(monkeypatch):
    chat = Status({m: (429, GEMINI_DAILY_429) for m in config.PROVIDERS["gemini"]["models"]})
    client = openai_client("gemini", chat, monkeypatch)
    with pytest.raises(LLMError) as info:
        client.structured("sys", [], ResponseDraft, "draft")
    assert info.value.fatal and str(info.value).startswith("gemini: daily quota reached (tried ")
    assert "RESOURCE_EXHAUSTED" not in str(info.value)


def test_billing_quota_is_fatal_without_trying_other_models(monkeypatch):
    first = config.PROVIDERS["openai"]["models"][0]
    chat = Status({first: (429, "Error code: 429 - {'error': {'code': 'insufficient_quota'}}")})
    client = openai_client("openai", chat, monkeypatch)
    with pytest.raises(LLMError, match="no remaining credit") as info:
        client.structured("sys", [], ResponseDraft, "draft")
    assert info.value.fatal and len(chat.calls) == 1


def test_per_minute_rate_limit_is_not_a_model_switch(monkeypatch):
    first = config.PROVIDERS["gemini"]["models"][0]
    chat = Status({first: (429, "Error code: 429 - quotaId GenerateRequestsPerMinutePerProjectPerModel")})
    client = openai_client("gemini", chat, monkeypatch)
    with pytest.raises(LLMError) as info:
        client.structured("sys", [], ResponseDraft, "draft")
    assert not info.value.fatal and client.model == first and not client.fallbacks


def test_sdk_does_not_retry_daily_quota_but_retries_per_minute(monkeypatch):
    """Against the real pinned SDK: a daily-quota 429 is raised at once instead of after ~1 min of backoff."""
    import httpx2

    first, second = config.PROVIDERS["gemini"]["models"][:2]
    seen = []
    per_minute_left = [1]

    def handler(request):
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == first:
            return httpx2.Response(429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
                {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})
        if per_minute_left[0]:
            per_minute_left[0] -= 1
            return httpx2.Response(429, headers={"retry-after-ms": "1"}, json={"error": {"message": "slow down"}})
        return httpx2.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(REPLY)}}]})

    client = LLMClient("AIza-sdk", provider="gemini")
    client.client = llm._client_class()(api_key="AIza-sdk", base_url="https://example.test/v1", max_retries=6,
                                        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert client.structured("sys", [], ResponseDraft, "draft").reply == "Hello."
    assert seen == [first, second, second]  # no retry of the daily quota; the per-minute 429 was retried
