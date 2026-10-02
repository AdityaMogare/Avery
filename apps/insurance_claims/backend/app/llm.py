"""Thin OpenAI wrapper: structured outputs validated with Pydantic."""

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
    def __init__(self, api_key: str, model: str | None = None):
        from openai import OpenAI

        self.model = model or config.OPENAI_MODEL
        self.client = OpenAI(api_key=api_key, base_url=config.OPENAI_BASE_URL)

    def _record(self, name: str, resp: Any, started: float) -> None:
        sink = USAGE_SINK.get()
        if sink is None:
            return
        usage = getattr(resp, "usage", None)
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        completion_details = getattr(usage, "completion_tokens_details", None)
        sink.append({
            "name": name, "model": self.model, "ms": round((time.perf_counter() - started) * 1000),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "cached_tokens": getattr(prompt_details, "cached_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "reasoning_tokens": getattr(completion_details, "reasoning_tokens", 0) or 0,
        })

    def structured(self, system: str, messages: list[dict[str, str]], schema: type[T], name: str) -> T:
        kwargs: dict[str, Any] = {}
        if config.OPENAI_REASONING_EFFORT:
            kwargs["reasoning_effort"] = config.OPENAI_REASONING_EFFORT
        started = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": to_strict_schema(schema), "strict": True},
                },
                **kwargs,
            )
        except Exception as exc:  # network, auth, schema errors all degrade the same way
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        self._record(name, resp, started)
        content = resp.choices[0].message.content or "{}"
        try:
            return schema.model_validate(json.loads(content))
        except Exception as exc:
            raise LLMError(f"invalid structured output: {exc}") from exc
