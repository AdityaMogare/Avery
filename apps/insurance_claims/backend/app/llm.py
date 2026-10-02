"""Thin OpenAI wrapper: structured outputs validated with Pydantic."""

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
    def __init__(self, api_key: str, model: str | None = None):
        from openai import OpenAI

        self.model = model or config.OPENAI_MODEL
        self.client = OpenAI(api_key=api_key, base_url=config.OPENAI_BASE_URL)

    def structured(self, system: str, messages: list[dict[str, str]], schema: type[T], name: str) -> T:
        kwargs: dict[str, Any] = {}
        if config.OPENAI_REASONING_EFFORT:
            kwargs["reasoning_effort"] = config.OPENAI_REASONING_EFFORT
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
        content = resp.choices[0].message.content or "{}"
        try:
            return schema.model_validate(json.loads(content))
        except Exception as exc:
            raise LLMError(f"invalid structured output: {exc}") from exc
