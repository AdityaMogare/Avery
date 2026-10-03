"""Thin provider-agnostic LLM wrapper: structured outputs validated with Pydantic.

Every supported provider (OpenAI, Gemini, OpenRouter) is reached through its OpenAI-compatible endpoint.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextvars import ContextVar
from typing import Any, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        # Fatal: the key or every model was rejected, so further calls this turn would fail the same way.
        self.fatal = fatal


# Model that worked for each (provider, key, requested chain). A new client is built per request, so without
# this every turn would hit a retired model's 404 again before falling back.
_RESOLVED_MODEL: dict[tuple[str, str, tuple[str, ...]], str] = {}


# Each model call appends a usage record to the active sink (one per turn). A ContextVar rather than a
# list on the client: the API shares one client across concurrent sessions.
USAGE_SINK: ContextVar[list[dict[str, Any]] | None] = ContextVar("usage_sink", default=None)


def summarize_usage(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals for a turn (or a conversation): tokens, model time and estimated USD cost."""
    def total(key: str) -> int:
        return sum(c.get(key, 0) for c in calls)

    prompt, cached, completion = total("prompt_tokens"), total("cached_tokens"), total("completion_tokens")
    cost = ((prompt - cached) * config.PRICE_INPUT_PER_M + cached * config.PRICE_CACHED_INPUT_PER_M
            + completion * config.PRICE_OUTPUT_PER_M) / 1_000_000
    return {"llm_calls": len(calls), "prompt_tokens": prompt, "cached_tokens": cached,
            "completion_tokens": completion, "reasoning_tokens": total("reasoning_tokens"),
            "llm_ms": total("ms"), "cost_usd": round(cost, 6),
            "by_stage": {name: sum(1 for c in calls if c["name"] == name) for name in dict.fromkeys(c["name"] for c in calls)}}


def to_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic schema into OpenAI strict json_schema form."""
    schema = model.model_json_schema()

    def fix(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: fix(v) for k, v in node.items() if k not in ("default", "title", "examples")}
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            return node
        if isinstance(node, list):
            return [fix(x) for x in node]
        return node

    return fix(schema)


class LLMClient:
    def __init__(self, api_key: str, model: str | None = None, provider: str | None = None):
        self.provider = config.detect_provider(api_key, provider)
        self.models = config.model_chain(self.provider, model)
        self._cache_key = (self.provider, hashlib.sha256(api_key.encode()).hexdigest()[:16], tuple(self.models))
        self.model = _RESOLVED_MODEL.get(self._cache_key, self.models[0])
        self.fallbacks: list[dict[str, str]] = []  # model switches since the pipeline last drained them
        base_url = config.LLM_BASE_URL or config.PROVIDERS[self.provider]["base_url"]
        # The SDK retries 429s and 5xx with exponential backoff and honours retry-after, except daily quotas.
        self.client = _client_class()(api_key=api_key, base_url=base_url, max_retries=config.LLM_MAX_RETRIES)
        self._json_object_only = False  # set once an endpoint rejects json_schema response_format

    def _record(self, name: str, started: float, *, prompt: int, cached: int, completion: int, reasoning: int = 0) -> None:
        sink = USAGE_SINK.get()
        if sink is None:
            return
        sink.append({
            "name": name, "model": self.model, "ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": prompt or 0, "cached_tokens": cached or 0,
            "completion_tokens": completion or 0, "reasoning_tokens": reasoning or 0,
        })

    def _next_model(self, reason: str) -> bool:
        """Step to the next model in the chain after the current one was reported unavailable."""
        remaining = self.models[self.models.index(self.model) + 1:] if self.model in self.models else []
        if not remaining:
            return False
        self.fallbacks.append({"from": self.model, "to": remaining[0], "reason": reason})
        self.model = _RESOLVED_MODEL[self._cache_key] = remaining[0]
        return True

    def structured(self, system: str, messages: list[dict[str, str]], schema: type[T], name: str) -> T:
        strict = to_strict_schema(schema)
        while True:
            try:
                content = self._openai_compatible(system, messages, strict, name)
                break
            except Exception as exc:  # network, auth, schema errors all degrade the same way
                status, msg = getattr(exc, "status_code", None), str(exc).lower()
                if status == 429 and "insufficient_quota" in msg:  # billing: every model on the account is out
                    raise LLMError(f"{self.provider}: this key has no remaining credit or quota.", fatal=True) from exc
                # Quotas are counted per model (Gemini's free tier allows 20 requests a day per model), so the
                # next model in the chain usually still has quota.
                reason = "daily_quota" if status == 429 and _daily_quota(msg) else (
                    "unavailable" if _model_unavailable(exc) else None)
                if reason:
                    if self._next_model(reason):
                        continue
                    what = "daily quota reached" if reason == "daily_quota" else "no model available to this key"
                    raise LLMError(f"{self.provider}: {what} (tried {', '.join(self.models)}). Try again later, set "
                                   f"another model in the Model field, or use another key.", fatal=True) from exc
                if status in (401, 403):
                    raise LLMError(f"{self.provider} rejected the API key ({status}): {_short(exc)}",
                                   fatal=True) from exc
                raise LLMError(f"{self.provider} {type(exc).__name__}: {_short(exc, 300)}") from exc
        try:
            return schema.model_validate(json.loads(_strip_fences(content or "{}")))
        except Exception as exc:
            raise LLMError(f"invalid structured output: {exc}") from exc

    def _openai_compatible(self, system: str, messages: list[dict[str, str]], strict: dict[str, Any], name: str) -> str:
        kwargs: dict[str, Any] = {}
        if self.provider == "openai" and config.OPENAI_REASONING_EFFORT:
            kwargs["reasoning_effort"] = config.OPENAI_REASONING_EFFORT
        if not self._json_object_only:
            try:
                return self._chat(system, messages, {
                    "type": "json_schema", "json_schema": {"name": name, "schema": strict, "strict": True}}, kwargs, name)
            except Exception as exc:
                if not _schema_unsupported(exc):
                    raise
                self._json_object_only = True
        # Fallback for endpoints/models without strict json_schema: JSON mode + schema in the prompt.
        system = f"{system}\n\nRespond with a single JSON object matching this JSON Schema:\n{json.dumps(strict)}"
        return self._chat(system, messages, {"type": "json_object"}, kwargs, name)

    def _chat(self, system: str, messages: list[dict[str, str]], response_format: dict[str, Any],
              kwargs: dict[str, Any], name: str) -> str:
        started = time.perf_counter()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            response_format=response_format,
            **kwargs,
        )
        usage = getattr(resp, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        completion_details = getattr(usage, "completion_tokens_details", None)
        self._record(
            name, started,
            prompt=getattr(usage, "prompt_tokens", 0) or 0,
            cached=getattr(prompt_details, "cached_tokens", 0) or 0,
            completion=getattr(usage, "completion_tokens", 0) or 0,
            reasoning=getattr(completion_details, "reasoning_tokens", 0) or 0,
        )
        return resp.choices[0].message.content or "{}"


def _schema_unsupported(exc: Exception) -> bool:
    """A 400 complaining about response_format/json_schema (rather than auth, model, network)."""
    msg = str(exc).lower()
    return getattr(exc, "status_code", None) in (400, 422) and ("response_format" in msg or "json_schema" in msg)


def _daily_quota(text: str) -> bool:
    """A 429 for a per-day quota (Gemini "...PerDay...", OpenRouter "free-models-per-day"). Retrying it within a
    turn only adds a minute of backoff, unlike a per-minute rate limit."""
    text = text.lower()
    return "perday" in text or "per-day" in text or "per day" in text


def _client_class():
    """The OpenAI SDK client, minus retries for daily-quota 429s. `_should_retry` is the SDK's private hook
    (openai is pinned in requirements.txt); if it were renamed the override is skipped and the SDK simply
    retries as before."""
    from openai import OpenAI

    class QuotaAwareOpenAI(OpenAI):
        def _should_retry(self, response) -> bool:
            if response.status_code == 429:
                try:
                    body = response.read().decode(errors="ignore")
                except Exception:
                    body = ""
                if _daily_quota(body) or "insufficient_quota" in body:
                    return False
            return super()._should_retry(response)

    return QuotaAwareOpenAI


def _model_unavailable(exc: Exception) -> bool:
    """The model id is unknown, retired or not enabled for this key (rather than auth, quota or network)."""
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return status == 404 or (status in (400, 403) and any(
        s in msg for s in ("model_not_found", "no longer available", "is not a valid model", "does not exist",
                           "not found for api version", "no endpoints found")))


def _short(exc: Exception, limit: int = 200) -> str:
    text = str(exc)
    return text if len(text) <= limit else text[:limit] + "…"


def _strip_fences(text: str) -> str:
    """JSON-mode models occasionally wrap output in ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text
