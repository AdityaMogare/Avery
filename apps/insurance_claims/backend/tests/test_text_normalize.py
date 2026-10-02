"""Spoken-form normalization: spoken digits, years, ordinal days and emails become written values;
ordinary words that happen to be numbers stay untouched."""

import pytest

from app.text_normalize import normalize_spoken

REWRITES = [
    ("SSN last four is four four seven two", "SSN last four is 4472"),
    ("last four four four seven two", "last four 4472"),
    ("ssn ends in double four seven two", "ssn ends in 4472"),
    ("phone six five oh, five two one, two eight three six", "phone 6505212836"),
    ("born nineteen eighty-five", "born 1985"),
    ("born nineteen eighty five", "born 1985"),
    ("year two thousand one", "year 2001"),
    ("twenty twenty six", "2026"),
    ("nineteen oh five", "1905"),
    ("DOB March fifteenth nineteen eighty five", "DOB March 15 1985"),
    ("the fifteenth of March, 1985", "March 15, 1985"),
    ("the twenty-first of August 1990", "August 21 1990"),
    ("the 15th of March 1985", "March 15 1985"),
    ("email is margaret at email dot com", "email is margaret@email.com"),
    ("ava dot lopez at email dot com", "ava.lopez@email.com"),
]

UNCHANGED = [
    "I have one claim and two questions",
    "First, I want to say thanks",
    "Oh, my name is Margaret Chen",
    "I'm calling at noon about my claim",
    "SSN last four is 4472",
    "DOB 1985-03-15",
    "I was there for the second time",
]


@pytest.mark.parametrize("spoken,written", REWRITES)
def test_rewrites(spoken, written):
    assert normalize_spoken(spoken) == written


@pytest.mark.parametrize("text", UNCHANGED)
def test_leaves_ordinary_words(text):
    assert normalize_spoken(text) == text


def test_spoken_identity_verifies_offline(offline_agent):
    from app.state import SessionState

    s = SessionState()
    offline_agent.start(s)
    offline_agent.handle(s, "My name is Margaret Chen, date of birth March fifteenth nineteen eighty five, "
                            "social last four is four four seven two.")
    assert s.verified
