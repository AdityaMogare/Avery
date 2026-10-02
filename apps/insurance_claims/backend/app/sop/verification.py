"""Deterministic identity verification. The LLM never decides whether someone is verified."""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Literal

from ..config import MIN_VERIFIED_FIELDS
from ..fixtures import Repository

FIELD_LABELS = {
    "name": "full name",
    "dob": "date of birth",
    "phone": "phone number",
    "email": "email address",
    "id_last4": "last 4 digits of your SSN or national ID",
}

_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%d.%m.%Y",
    "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y",
)


def normalize_name(value: str) -> str:
    value = value.casefold().translate(str.maketrans("", "", string.punctuation))
    return " ".join(value.split())


def normalize_dob(value: str) -> str | None:
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip(), flags=re.I)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def normalize_last4(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    return digits[-4:] if len(digits) >= 4 else None


def name_matches(provided: str, record: dict[str, Any]) -> bool:
    candidates = [record["name"], *record.get("name_aliases", [])]
    p = normalize_name(provided)
    for c in map(normalize_name, candidates):
        if p == c or p.replace(" ", "") == c.replace(" ", ""):
            return True
        if sorted(p.split()) == sorted(c.split()):  # "Chen Margaret"
            return True
        if SequenceMatcher(None, p, c).ratio() >= 0.92:  # minor typos only
            return True
    return False


def field_matches(field_name: str, provided: str, record: dict[str, Any]) -> bool:
    if field_name == "name":
        return name_matches(provided, record)
    if field_name == "dob":
        return normalize_dob(provided) == record["dob"]
    if field_name == "phone":
        p = normalize_phone(provided)
        return p is not None and p in {normalize_phone(x) for x in [record["phone"], *record.get("phone_aliases", [])]}
    if field_name == "email":
        return normalize_email(provided) in {normalize_email(x) for x in [record["email"], *record.get("email_aliases", [])]}
    if field_name == "id_last4":
        return normalize_last4(provided) == record["id_last4"]
    return False


@dataclass
class VerificationResult:
    outcome: Literal["verified", "insufficient", "failed"]
    party_id: str | None = None
    matched_fields: list[str] = field(default_factory=list)
    provided_fields: list[str] = field(default_factory=list)
    missing_count: int = 0


def verify(provided: dict[str, str], repo: Repository, policy_number: str | None = None) -> VerificationResult:
    """Verify when >= MIN_VERIFIED_FIELDS provided fields match one record and none conflict.

    The policy number narrows the lookup but never counts toward the threshold. Callers must not be
    told which field failed (avoids an enumeration oracle).
    """
    provided = {k: v for k, v in provided.items() if v}
    provided_fields = sorted(provided)
    if len(provided) < MIN_VERIFIED_FIELDS:
        return VerificationResult("insufficient", provided_fields=provided_fields,
                                  missing_count=MIN_VERIFIED_FIELDS - len(provided))

    records = repo.policyholders
    if policy_number:
        narrowed = [r for r in records if r["policy_number"].upper() == policy_number.upper().replace(" ", "")]
        records = narrowed or records

    for record in records:
        matched = [f for f, v in provided.items() if field_matches(f, v, record)]
        conflicts = [f for f in provided if f not in matched]
        if len(matched) >= MIN_VERIFIED_FIELDS and not conflicts:
            return VerificationResult("verified", party_id=record["party_id"],
                                      matched_fields=sorted(matched), provided_fields=provided_fields)
    return VerificationResult("failed", provided_fields=provided_fields)


_RELATION_GROUPS = {
    "child": {"son", "daughter", "child"},
    "parent": {"mother", "father", "mom", "dad", "parent"},
    "spouse": {"wife", "husband", "spouse", "partner"},
}
_INVERSE = {"child": "parent", "parent": "child", "spouse": "spouse"}


def _relation_group(word: str) -> str | None:
    return next((g for g, words in _RELATION_GROUPS.items() if word in words), None)


def relationship_compatible(recorded: str, stated: str) -> bool:
    """Caller may state either side: "I'm her son" or "calling for my mother" both fit a recorded "son"."""
    recorded, stated = normalize_name(recorded), normalize_name(stated)
    if recorded == stated:
        return True
    g_rec, g_stated = _relation_group(recorded), _relation_group(stated)
    return g_rec is not None and g_stated in {g_rec, _INVERSE[g_rec]}


def representative_authorized(rep_name: str | None, relationship: str | None, party_id: str,
                              repo: Repository) -> dict[str, Any] | None:
    if not rep_name:
        return None
    for rep in repo.representatives_for(party_id):
        if normalize_name(rep["rep_name"]) == normalize_name(rep_name) and (
            not relationship or relationship_compatible(rep["relationship"], relationship)
        ):
            return rep
    return None
