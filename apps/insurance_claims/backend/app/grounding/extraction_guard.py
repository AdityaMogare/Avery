"""Input-side grounding: every value the understanding step extracts must be traceable to the caller's
own message. Live finding: gpt-5.4-nano turned "dob is 12/03/200" into "2000-12-03" — an invented year
that then consumed a verification attempt. Ungrounded values are dropped (and asked about), never used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..sop.verification import FIELD_LABELS, normalize_dob
from ..state import MONTHS
from ..understanding import TurnUnderstanding

FIELD_FOR_ATTR = {"full_name": "name", "dob": "dob", "phone": "phone", "email": "email", "id_last4": "id_last4"}


@dataclass
class GuardResult:
    understanding: TurnUnderstanding
    rejected: dict[str, str] = field(default_factory=dict)   # field -> what the caller wrote (or reason)
    corrected: dict[str, str] = field(default_factory=dict)  # field -> literal value used instead


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _numbers(s: str) -> set[int]:
    return {int(n) for n in re.findall(r"\d+", s)}


def _dob_grounded(value: str, message: str) -> bool:
    iso = normalize_dob(value)
    if not iso:
        return False
    year, month, day = (int(x) for x in iso.split("-"))
    low = message.casefold()
    nums = _numbers(message)
    year_ok = re.search(rf"\b{year}\b", message) is not None
    month_ok = month in nums or MONTHS[month - 1].casefold() in low or MONTHS[month - 1][:3].casefold() in low
    return year_ok and month_ok and day in nums


def _raw_date_like(message: str) -> str | None:
    m = re.search(r"\b\d{1,4}[/-]\d{1,2}[/-]\d{1,4}\b", message)
    return m.group(0) if m else None


def _literal_name(extracted: str, message: str) -> str | None:
    """Return the caller's literal spelling if the model normalized it, None if no close span exists."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", message)
    n = len(extracted.split())
    target = extracted.casefold()
    best, best_ratio = None, 0.0
    for i in range(len(words) - n + 1):
        span = " ".join(words[i:i + n])
        ratio = SequenceMatcher(None, span.casefold(), target).ratio()
        if ratio > best_ratio:
            best, best_ratio = span, ratio
    return best if best_ratio >= 0.8 else None


def ground_understanding(und: TurnUnderstanding, message: str) -> GuardResult:
    res = GuardResult(understanding=und.model_copy())
    u = res.understanding
    low = message.casefold()
    msg_digits = _digits(message)

    # A representative's own name is not the policyholder's name (live nano mix-up: "I'm John Smith calling
    # for my wife Margaret Chen" -> full_name="John Smith"). Take the name after "for/behalf of", else drop.
    if u.full_name and u.representative_name and u.full_name.casefold() == u.representative_name.casefold():
        m = re.search(r"\b(?:for|behalf of)\s+(?:my\s+)?(?:[a-z]+\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", message)
        if m and m.group(1).casefold() != u.representative_name.casefold():
            res.corrected["name"] = m.group(1)
            u.full_name = m.group(1)
        else:
            res.rejected["name"] = "the representative's own name, not the policyholder's"
            u.full_name = None

    if u.full_name:
        if u.full_name.casefold() not in low:
            literal = _literal_name(u.full_name, message)
            if literal:
                res.corrected["name"] = literal
                u.full_name = literal  # use what the caller actually typed, never the model's "fix"
            else:
                res.rejected["name"] = "not found in the message"
                u.full_name = None
    if u.dob and not _dob_grounded(u.dob, message):
        # Live (nano): "Why didn't that work?" came back with the DOB from an earlier turn. With no date-like
        # text in the message the value was invented, not misheard, so it is dropped without a clarify.
        said_a_date = bool(re.search(r"\d", message)) or any(m.casefold()[:3] in low for m in MONTHS)
        res.rejected["dob"] = _raw_date_like(message) or ("unclear" if said_a_date else "not found in the message")
        u.dob = None
    if u.id_last4 and u.id_last4 not in msg_digits:
        res.rejected["id_last4"] = "not found in the message"
        u.id_last4 = None
    if u.phone and _digits(u.phone)[-10:] not in msg_digits:
        res.rejected["phone"] = "not found in the message"
        u.phone = None
    if u.email and u.email.casefold() not in low:
        res.rejected["email"] = "not found in the message"
        u.email = None
    # Claim hints must also come from the caller's words (live: nano tagged a timing question with a case
    # status, which sent the controller to "no matching claim").
    hint_words = {
        "case_type": {"healthcare": ("health", "medical", "hospital", "doctor"), "dental": ("dental", "dentist", "teeth"),
                      "auto": ("auto", "car", "vehicle", "accident")},
        "case_status": {"denied": ("denied", "denial", "rejected", "declined"), "open": ("open", "pending", "in progress"),
                        "closed": ("closed", "settled", "paid", "completed", "finished")},
    }
    for attr, table in hint_words.items():
        value = getattr(u, attr)
        if value and not any(w in low for w in table.get(value, ())):
            setattr(u, attr, None)
            res.rejected[attr] = "not stated in the message"
    if u.case_month and not any(m.casefold() in low or m[:3].casefold() in low for m in [MONTHS[u.case_month - 1]]):
        u.case_month = None
        res.rejected["case_month"] = "not stated in the message"
    if u.case_year and str(u.case_year) not in message:
        u.case_year = None
        res.rejected["case_year"] = "not stated in the message"
    for attr in ("policy_number", "case_id"):
        value = getattr(u, attr)
        if value and _digits(value) not in msg_digits:
            setattr(u, attr, None)
            res.rejected[attr] = "not found in the message"
    return res


def describe_rejections(rejected: dict[str, str]) -> list[str]:
    """Fields to ask the caller to restate. A value the model invented ("not found in the message") is
    dropped silently: asking the caller to "restate" something they never said is itself ungrounded."""
    out = []
    for f, raw in rejected.items():
        if f in FIELD_LABELS and raw != "not found in the message":
            label = FIELD_LABELS[f]
            out.append(f"{label} (you wrote '{raw}')" if raw not in ("unclear", "not found in the message") else label)
    return out
