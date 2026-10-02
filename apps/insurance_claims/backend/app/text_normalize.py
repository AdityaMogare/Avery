"""Spoken-form normalization for format-rigid identity values.

The fixtures describe an *audio* agent, so callers (and speech-to-text) produce "four four seven two",
"nineteen eighty-five" or "margaret at email dot com". The LLM sees the raw message; this normalized copy
feeds the regex backfill and the input grounding guard, so a spoken value is neither missed nor rejected
as "not in the message".

Deliberately conservative: a lone number word ("one claim", "last four") is left alone. Only runs that can
only be a digit string, a year, an ordinal day or a spelled-out email are rewritten.
"""

from __future__ import annotations

import re

DIGITS = {"zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
          "seven": 7, "eight": 8, "nine": 9}
TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
        "ninety": 90}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
            "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
            "nineteenth": 19, "twentieth": 20, "thirtieth": 30}
MULT = {"double": 2, "triple": 3}

_WORD = r"[A-Za-z]+"
_TOKEN = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]+|\s+")


def _two_digit(tokens: list[str], i: int) -> tuple[int, int] | None:
    """Parse a 10-99 number at tokens[i] ("fifteen", "eighty five", "eighty-five"); return (value, next_i)."""
    w = tokens[i].lower()
    if w in TEENS:
        return TEENS[w], i + 1
    if w in TENS:
        j = _skip_join(tokens, i + 1)
        if j < len(tokens) and tokens[j].lower() in DIGITS and tokens[j].lower() not in ("oh", "o", "zero"):
            return TENS[w] + DIGITS[tokens[j].lower()], j + 1
        return TENS[w], i + 1
    return None


def _skip_join(tokens: list[str], i: int) -> int:
    """Skip one whitespace or hyphen separator."""
    if i < len(tokens) and (tokens[i].isspace() or tokens[i] == "-"):
        return i + 1
    return i


def _year(tokens: list[str], i: int) -> tuple[int, int] | None:
    """'nineteen eighty five' -> 1985, 'two thousand one' -> 2001, 'twenty twenty six' -> 2026."""
    w = tokens[i].lower()
    if w == "two":
        j = _skip_join(tokens, i + 1)
        if j < len(tokens) and tokens[j].lower() == "thousand":
            k = _skip_join(tokens, j + 1)
            if k < len(tokens) and tokens[k].lower() == "and":
                k = _skip_join(tokens, k + 1)
            if k < len(tokens):
                if (two := _two_digit(tokens, k)):
                    return 2000 + two[0], two[1]
                if tokens[k].lower() in DIGITS and tokens[k].lower() not in ("oh", "o"):
                    return 2000 + DIGITS[tokens[k].lower()], k + 1
            return 2000, j + 1
        return None
    first = _two_digit(tokens, i)
    if not first or first[0] not in (19, 20):
        return None
    j = _skip_join(tokens, first[1])
    if j >= len(tokens):
        return None
    # "nineteen oh five"
    if tokens[j].lower() in ("oh", "o"):
        k = _skip_join(tokens, j + 1)
        if k < len(tokens) and tokens[k].lower() in DIGITS:
            return first[0] * 100 + DIGITS[tokens[k].lower()], k + 1
        return None
    second = _two_digit(tokens, j)
    if second and second[0] >= 10:
        return first[0] * 100 + second[0], second[1]
    return None


def _digit_run(tokens: list[str], i: int) -> tuple[str, int] | None:
    """Two or more spoken digits ('four four seven two', 'double four', 'five oh three') -> digit string."""
    out: list[str] = []
    j = end = i
    while j < len(tokens):
        w = tokens[j].lower()
        if w in MULT:
            k = _skip_join(tokens, j + 1)
            if k >= len(tokens) or tokens[k].lower() not in DIGITS:
                break
            out.append(str(DIGITS[tokens[k].lower()]) * MULT[w])
            j = end = k + 1
        elif w in DIGITS and not (w in ("oh", "o") and not out):  # "oh" never starts a run ("oh, my name")
            out.append(str(DIGITS[w]))
            j = end = j + 1
        else:
            break
        while j < len(tokens) and (tokens[j].isspace() or tokens[j] in ("-", ",")):
            j += 1
    digits = "".join(out)
    return (digits, end) if len(digits) >= 2 else None


def _spoken_numbers(text: str) -> str:
    tokens = _TOKEN.findall(text)
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        low = tok.lower()
        prev_word = next((t.lower() for t in reversed(out) if not t.isspace()), "")
        if not re.fullmatch(_WORD, tok) or prev_word == "last" and low == "four":
            out.append(tok)
            i += 1
            continue
        if (y := _year(tokens, i)):
            out.append(str(y[0]))
            i = y[1]
            continue
        if (run := _digit_run(tokens, i)):
            out.append(run[0])
            i = run[1]
            continue
        out.append(tok)
        i += 1
    return "".join(out)


_SPOKEN_EMAIL = re.compile(
    r"\b([a-z0-9]+(?:\s+(?:dot|underscore)\s+[a-z0-9]+)*)\s+at\s+([a-z0-9-]+(?:\s+dot\s+[a-z0-9-]+)*\s+dot\s+"
    r"(?:com|org|net|edu|gov|io|co|us))\b", re.I)


def _spoken_email(text: str) -> str:
    def fix(m: re.Match) -> str:
        local = re.sub(r"\s+dot\s+", ".", m.group(1), flags=re.I)
        local = re.sub(r"\s+underscore\s+", "_", local, flags=re.I)
        domain = re.sub(r"\s+dot\s+", ".", m.group(2), flags=re.I)
        return f"{local}@{domain}"
    return _SPOKEN_EMAIL.sub(fix, text)


_MONTHS = "|".join(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                     "October", "November", "December"])
_ORD = r"(?:(?:twenty|thirty)[\s-]+)?(?:%s)" % "|".join(sorted(ORDINALS, key=len, reverse=True))
# Ordinals only count next to a month ("March fifteenth", "the fifteenth of March"); "first" alone is a word.
_MONTH_ORD = re.compile(r"\b(%s)\s+(?:the\s+)?(%s)\b" % (_MONTHS, _ORD), re.I)
_ORD_OF_MONTH = re.compile(r"\b(?:the\s+)?(%s)\s+of\s+(%s)\b" % (_ORD, _MONTHS), re.I)
_DAY_OF_MONTH = re.compile(r"\b(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(%s)\b" % _MONTHS, re.I)


def _ordinal_value(phrase: str) -> int:
    parts = re.split(r"[\s-]+", phrase.lower())
    return sum(TENS.get(p, 0) + ORDINALS.get(p, 0) for p in parts)


def normalize_spoken(text: str) -> str:
    """Rewrite spoken digits, years, ordinal days and emails into their written form."""
    text = _MONTH_ORD.sub(lambda m: f"{m.group(1)} {_ordinal_value(m.group(2))}", text)
    text = _ORD_OF_MONTH.sub(lambda m: f"{m.group(2)} {_ordinal_value(m.group(1))}", text)
    text = _spoken_numbers(text)
    text = _spoken_email(text)
    # "the 15 of March 1985" -> "March 15 1985" so the long-date pattern matches.
    text = _DAY_OF_MONTH.sub(lambda m: f"{m.group(2)} {m.group(1)}", text)
    return text
