"""Deterministic grounding verifier ("supervisor") run on every agent reply before it is sent.

Checks that every checkable factual token in the reply (case IDs, money, dates, durations, document
names, record PII) appears in the turn's FactSheet, that citations point at real facts, and that no
claim data leaks before verification or across policyholders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..fixtures import Repository
from ..sop.verification import normalize_phone
from ..state import MONTHS, Phase, SessionState
from .factsheet import FactSheet
from .gates import check_gates, normalize_quotes

CASE_RE = re.compile(r"\bCL-?\d{3,}\b", re.I)
POLICY_RE = re.compile(r"\bPOL-?\d{3,}\b", re.I)
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?|\b\d[\d,]*\.\d{2}\b(?:\s?(?:USD|dollars))?")
ISO_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
LONG_DATE_RE = re.compile(r"\b(%s)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b" % "|".join(MONTHS), re.I)
NUM_WORDS = "one|two|three|four|five|six|seven|eight|nine|ten|fourteen|fifteen|thirty|sixty|ninety"
DURATION_RE = re.compile(rf"\b(\d+|{NUM_WORDS}|a few|a couple of)\s+(business\s+|calendar\s+|working\s+)?(day|week|month|hour)s?\b", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass
class VerifierResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    checked_tokens: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "violations": self.violations, "checked_tokens": self.checked_tokens}


def _money(s: str) -> float:
    return float(re.sub(r"[^\d.]", "", s) or 0)


def _fact_dates(values: list[str]) -> set[str]:
    return {d for v in values for d in ISO_RE.findall(v)}


def _norm_text(s: str) -> str:
    return " ".join(re.sub(r"[^\w@.+-]", " ", s.casefold()).split())


def verify_reply(reply: str, claims: list[dict[str, Any]], facts: FactSheet, state: SessionState,
                 repo: Repository, actions: list[str] | None = None) -> VerifierResult:
    reply = normalize_quotes(reply)
    violations: list[str] = []
    tokens: dict[str, list[str]] = {}
    values = facts.values()
    blob = _norm_text(" || ".join(values))
    caller_said = _norm_text(" ".join(m.content for m in state.transcript if m.role == "user"))
    verified_party = state.verification.party_id if state.verified else None

    # 1. Citations must reference facts that exist this turn.
    for c in claims:
        for fid in c.get("fact_ids", []):
            if fid not in facts:
                violations.append(f"citation to unknown fact id '{fid}'")

    # 2. Case IDs: must be in facts, must belong to the verified caller.
    for raw in CASE_RE.findall(reply):
        cid = raw.upper() if "-" in raw else raw.upper().replace("CL", "CL-")
        tokens.setdefault("case_ids", []).append(cid)
        claim = repo.claim(cid)
        if cid.casefold() in caller_said:
            continue  # repeating an id the caller typed reveals nothing
        if claim and claim["party_id"] != verified_party:
            violations.append(f"case {cid} does not belong to a verified caller (cross-party or pre-verification leak)")
        elif cid.casefold() not in blob:
            violations.append(f"case id {cid} not present in facts")

    # 3. Policy numbers.
    for raw in POLICY_RE.findall(reply):
        tokens.setdefault("policy_numbers", []).append(raw)
        if raw.casefold() not in blob and raw.casefold() not in caller_said:
            violations.append(f"policy number {raw} not grounded")

    # 4. Money amounts.
    fact_amounts = {_money(m) for v in values for m in MONEY_RE.findall(v)}
    for raw in MONEY_RE.findall(reply):
        tokens.setdefault("money", []).append(raw)
        if _money(raw) not in fact_amounts:
            violations.append(f"amount '{raw.strip()}' not present in facts")

    # 5. Dates (ISO and "March 18, 2026" / "March 18").
    fact_dates = _fact_dates(values)
    for raw in ISO_RE.findall(reply):
        tokens.setdefault("dates", []).append(raw)
        if raw not in fact_dates and raw not in caller_said:
            violations.append(f"date {raw} not present in facts")
    for month, day, year in LONG_DATE_RE.findall(reply):
        m = MONTHS.index(month.capitalize()) + 1
        tokens.setdefault("dates", []).append(f"{month} {day} {year}".strip())
        ok = any(int(d[5:7]) == m and int(d[8:10]) == int(day) and (not year or d[:4] == year) for d in fact_dates)
        if not ok:
            try:  # caller's own DOB said back is fine only if they said it
                iso = datetime(int(year or 1900), m, int(day)).date().isoformat()
            except ValueError:
                iso = ""
            if not iso or iso not in caller_said:
                violations.append(f"date '{f'{month} {day} {year}'.strip()}' not present in facts")

    # 6. Durations / timelines ("within 30 days", "a few business days").
    for match in DURATION_RE.finditer(reply):
        phrase = _norm_text(match.group(0))
        tokens.setdefault("durations", []).append(phrase)
        unit = match.group(3).lower()
        if phrase not in blob and not re.search(rf"{re.escape(match.group(1).lower())}\s+(business\s+)?{unit}", blob):
            violations.append(f"timeline '{match.group(0)}' not present in facts")

    # 7. Document names: only documents present in this turn's facts may be named.
    for doc in sorted(repo.all_document_names(), key=len, reverse=True):
        short = doc.replace("original ", "").replace("treating provider ", "")
        for name in {doc, short}:
            if re.search(rf"\b{re.escape(name)}\b", reply, re.I):
                tokens.setdefault("documents", []).append(name)
                if name.casefold() not in blob and name.casefold() not in caller_said:
                    violations.append(f"document '{name}' not present in facts")

    # 8. Record PII must never be read out unless the caller said it (masked email facts are fine).
    for p in repo.policyholders:
        for key in ("phone", "email", "dob"):
            val = p[key]
            present = (normalize_phone(val) in {normalize_phone(x) for x in PHONE_RE.findall(reply)}
                       if key == "phone" else val.casefold() in reply.casefold())
            if present and val.casefold() not in caller_said and (key != "phone" or normalize_phone(val) not in re.sub(r"\D", "", caller_said)):
                violations.append(f"record {key} disclosed")
        if re.search(rf"\b{p['id_last4']}\b", reply) and p["id_last4"] not in caller_said:
            violations.append("record id last-4 disclosed")
        if p["party_id"] != verified_party and p["name"].casefold() in reply.casefold() \
                and p["name"].casefold() not in caller_said:
            violations.append(f"another policyholder's name disclosed")

    # 9. Phase gate: nothing from a claim record may be in play before verification.
    if not state.verified and facts.has_claim_data():
        violations.append("claim facts present before verification")
    if state.phase == Phase.PROCESS_CASE and facts.has_claim_data() and tokens and not claims:
        violations.append("factual reply in PROCESS_CASE without citations")

    # 10. Each claim's own tokens must be supported by the facts it cites.
    #     A case id is supported when it is the cited facts' subject (claim.<ID>.*) or in their values.
    for c in claims:
        ids = [f for f in c.get("fact_ids", []) if f in facts]
        cited = _norm_text(" ".join(facts.get(f).value for f in ids))
        subjects = {f.split(".")[1].casefold() for f in ids if f.startswith("claim.") and f.count(".") >= 2}
        for raw in CASE_RE.findall(c.get("text", "")) + MONEY_RE.findall(c.get("text", "")):
            needle = raw.casefold() if CASE_RE.fullmatch(raw) else None
            if needle and needle not in cited and needle not in subjects:
                violations.append(f"claim '{c.get('text', '')[:60]}' cites facts that do not contain {raw}")
            elif not needle and _money(raw) not in {_money(m) for m in MONEY_RE.findall(cited)}:
                violations.append(f"claim '{c.get('text', '')[:60]}' cites facts that do not contain {raw}")

    # 11. Behavioural boundary gates (commitments, outcome predictions, capabilities, state, addressing, scope).
    violations.extend(check_gates(reply, facts, state, actions, repo))

    return VerifierResult(ok=not violations, violations=sorted(set(violations)), checked_tokens=tokens)
