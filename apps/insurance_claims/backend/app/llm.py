"""Thin provider-agnostic LLM wrapper: structured outputs validated with Pydantic.

Anthropic keys use the Anthropic SDK; every other provider goes through its OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
import time
from contextvars import ContextVar
from typing import Any, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


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
        self.model = model or config.default_model(self.provider)
        if self.provider == "anthropic":
            from anthropic import Anthropic

            # Both SDKs retry 429s and 5xx with exponential backoff and honour retry-after.
            self.client = Anthropic(api_key=api_key, max_retries=config.LLM_MAX_RETRIES)
        else:
            from openai import OpenAI

            base_url = config.LLM_BASE_URL or config.PROVIDERS[self.provider]["base_url"]
            self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=config.LLM_MAX_RETRIES)
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

    def structured(self, system: str, messages: list[dict[str, str]], schema: type[T], name: str) -> T:
        strict = to_strict_schema(schema)
        try:
            if self.provider == "anthropic":
                content = self._anthropic(system, messages, strict, name)
            else:
                content = self._openai_compatible(system, messages, strict, name)
        except LLMError:
            raise
        except Exception as exc:  # network, auth, schema errors all degrade the same way
            raise LLMError(f"{self.provider} {type(exc).__name__}: {exc}") from exc
        try:
            return schema.model_validate(json.loads(_strip_fences(content or "{}")))
        except Exception as exc:
            raise LLMError(f"invalid structured output: {exc}") from exc

    def _anthropic(self, system: str, messages: list[dict[str, str]], strict: dict[str, Any], name: str) -> str:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": strict}}
        if "haiku" not in self.model:  # effort is rejected by Haiku; low keeps per-turn latency down elsewhere
            output_config["effort"] = "low"
        started = time.perf_counter()
        resp = self.client.messages.create(
            model=self.model, max_tokens=16000, system=system, messages=messages, output_config=output_config,
        )
        usage = getattr(resp, "usage", None)
        self._record(name, started, prompt=getattr(usage, "input_tokens", 0) or 0,
                     cached=getattr(usage, "cache_read_input_tokens", 0) or 0,
                     completion=getattr(usage, "output_tokens", 0) or 0)
        if resp.stop_reason == "refusal":
            raise LLMError("anthropic refusal")
        return next((b.text for b in resp.content if b.type == "text"), "")

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


def _strip_fences(text: str) -> str:
    """JSON-mode models occasionally wrap output in ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text
