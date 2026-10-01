"""Identity gate: deterministic, >= 3 matching fields, no conflicts, normalization and aliases."""

import pytest

from app.sop.verification import normalize_dob, normalize_phone, representative_authorized, verify


def test_three_fields_verify(repo):
    r = verify({"name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472"}, repo)
    assert r.outcome == "verified" and r.party_id == "P9"


def test_two_fields_insufficient(repo):
    r = verify({"name": "Margaret Chen", "dob": "1985-03-15"}, repo)
    assert r.outcome == "insufficient" and r.missing_count == 1


def test_policy_number_does_not_count(repo):
    r = verify({"name": "Margaret Chen", "dob": "1985-03-15"}, repo, policy_number="POL-9921")
    assert r.outcome == "insufficient"


def test_any_conflicting_field_fails_even_with_three_matches(repo):
    r = verify({"name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "4472", "phone": "5550000000"}, repo)
    assert r.outcome == "failed"


def test_fields_split_across_two_people_fail(repo):
    # Margaret's name + DOB with Ava's SSN digits must not verify anyone.
    assert verify({"name": "Margaret Chen", "dob": "1985-03-15", "id_last4": "9180"}, repo).outcome == "failed"


@pytest.mark.parametrize("raw", ["1985-03-15", "03/15/1985", "March 15, 1985", "15 March 1985", "March 15th, 1985"])
def test_dob_formats(raw):
    assert normalize_dob(raw) == "1985-03-15"


@pytest.mark.parametrize("raw", ["+16505212836", "650-521-2836", "(650) 521 2836", "1 650 521 2836"])
def test_phone_formats(raw):
    assert normalize_phone(raw) == "6505212836"


def test_name_alias_and_email_alias(repo):
    r = verify({"name": "Yaven Li", "email": "YAWEN.LI@example.com", "id_last4": "5317"}, repo)
    assert r.outcome == "verified" and r.party_id == "P13"


def test_national_id_counts_as_last4(repo):
    r = verify({"name": "Ma Tian", "dob": "09/10/1964", "id_last4": "6688"}, repo)
    assert r.outcome == "verified" and r.party_id == "P12"


def test_name_order_and_case_insensitive(repo):
    assert verify({"name": "chen margaret", "email": "Margaret@Email.com", "phone": "650.521.2836"}, repo).outcome == "verified"


def test_representative_authorization(repo):
    assert representative_authorized("David Chen", "son", "P9", repo)
    assert representative_authorized("David Chen", "husband", "P9", repo) is None
    assert representative_authorized("John Smith", "husband", "P9", repo) is None
