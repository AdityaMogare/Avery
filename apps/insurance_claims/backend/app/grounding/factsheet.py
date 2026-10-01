"""Atomic, ID-addressable facts. Every claim the agent makes must cite one of these."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Source = Literal["claim_record", "policyholder_record", "guideline", "schema", "session", "caller", "derived"]


@dataclass
class Fact:
    id: str
    value: str
    source: Source


@dataclass
class FactSheet:
    facts: dict[str, Fact] = field(default_factory=dict)

    def add(self, fact_id: str, value: object, source: Source) -> None:
        if value is None or value == "" or value == []:
            return
        if isinstance(value, list):
            value = ", ".join(map(str, value))
        self.facts[fact_id] = Fact(fact_id, str(value), source)

    def merge(self, other: "FactSheet") -> None:
        self.facts.update(other.facts)

    def __contains__(self, fact_id: str) -> bool:
        return fact_id in self.facts

    def get(self, fact_id: str) -> Fact | None:
        return self.facts.get(fact_id)

    def values(self, sources: set[str] | None = None) -> list[str]:
        return [f.value for f in self.facts.values() if sources is None or f.source in sources]

    def has_claim_data(self) -> bool:
        return any(f.source == "claim_record" for f in self.facts.values())

    def render(self) -> str:
        return "\n".join(f"[{f.id}] ({f.source}) {f.value}" for f in self.facts.values()) or "(no facts)"

    def as_list(self) -> list[dict[str, str]]:
        return [{"id": f.id, "value": f.value, "source": f.source} for f in self.facts.values()]
