"""Thin provider-agnostic LLM wrapper: structured outputs validated with Pydantic.

Anthropic keys use the Anthropic SDK; every other provider goes through its OpenAI-compatible endpoint.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


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

            self.client = Anthropic(api_key=api_key)
        else:
            from openai import OpenAI

            base_url = config.LLM_BASE_URL or config.PROVIDERS[self.provider]["base_url"]
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._json_object_only = False  # set once an endpoint rejects json_schema response_format

    def structured(self, system: str, messages: list[dict[str, str]], schema: type[T], name: str) -> T:
        strict = to_strict_schema(schema)
        try:
            if self.provider == "anthropic":
                content = self._anthropic(system, messages, strict)
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

    def _anthropic(self, system: str, messages: list[dict[str, str]], strict: dict[str, Any]) -> str:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": strict}}
        if "haiku" not in self.model:  # effort is rejected by Haiku; low keeps per-turn latency down elsewhere
            output_config["effort"] = "low"
        resp = self.client.messages.create(
            model=self.model, max_tokens=16000, system=system, messages=messages, output_config=output_config,
        )
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
                    "type": "json_schema", "json_schema": {"name": name, "schema": strict, "strict": True}}, kwargs)
            except Exception as exc:
                if not _schema_unsupported(exc):
                    raise
                self._json_object_only = True
        # Fallback for endpoints/models without strict json_schema: JSON mode + schema in the prompt.
        system = f"{system}\n\nRespond with a single JSON object matching this JSON Schema:\n{json.dumps(strict)}"
        return self._chat(system, messages, {"type": "json_object"}, kwargs)

    def _chat(self, system: str, messages: list[dict[str, str]], response_format: dict[str, Any],
              kwargs: dict[str, Any]) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            response_format=response_format,
            **kwargs,
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
