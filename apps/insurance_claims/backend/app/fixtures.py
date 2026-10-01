"""Read-only repository over the starter fixture files."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config


class Repository:
    def __init__(self, fixtures_dir: Path):
        self.dir = fixtures_dir
        self.policyholders: list[dict[str, Any]] = self._load("policyholders.json")
        self.claims: list[dict[str, Any]] = self._load("claims.json")
        self.representatives: list[dict[str, Any]] = self._load("representatives.json")
        self.consent_scenarios: dict[str, Any] = self._load("consent_scenarios.json")
        self.guideline: dict[str, Any] = self._load("required_document_guideline.json")
        self.claim_schema: dict[str, Any] = self._load("claim_schema.json")

    def _load(self, name: str) -> Any:
        return json.loads((self.dir / name).read_text())

    def policyholder(self, party_id: str) -> dict[str, Any] | None:
        return next((p for p in self.policyholders if p["party_id"] == party_id), None)

    def claims_for(self, party_id: str) -> list[dict[str, Any]]:
        return [c for c in self.claims if c["party_id"] == party_id]

    def claim(self, case_id: str) -> dict[str, Any] | None:
        return next((c for c in self.claims if c["case_id"].upper() == case_id.upper()), None)

    def representatives_for(self, party_id: str) -> list[dict[str, Any]]:
        return [r for r in self.representatives if r["buyer_party_id"] == party_id]

    def all_document_names(self) -> set[str]:
        names = {d for c in self.claims for d in c.get("documents_needed", [])}
        names |= set(self.guideline.get("document_guidance", {}))
        return names


@lru_cache(maxsize=1)
def get_repo() -> Repository:
    return Repository(config.FIXTURES_DIR)
