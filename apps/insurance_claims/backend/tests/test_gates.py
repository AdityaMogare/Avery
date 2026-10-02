"""Boundary gates G1-G6: each test plants exactly one violation seen in live evals or the UI."""

import pytest

from app.grounding.factsheet import FactSheet
from app.grounding.gates import check_gates
from app.state import Message, Phase, SessionState, Slot


def verified_state() -> SessionState:
    s = SessionState(phase=Phase.PROCESS_CASE)
    s.verification.status, s.verification.party_id = "verified", "P9"
    s.selected_case_id = "CL-2048"
    return s


def sop_facts(**extra) -> FactSheet:
    f = FactSheet()
    f.add("sop.scope", "this line helps only with the caller's insurance policy and claims", "session")
    f.add("sop.human_transfer", "a human representative can be connected at any time on request", "session")
    for k, v in extra.items():
        f.add(k.replace("__", "."), v, "session")
    return f


def gates(reply, state=None, facts=None, actions=None):
    return check_gates(reply, facts if facts is not None else sop_facts(), state or verified_state(), actions)


# --- G1 commitments ------------------------------------------------------------------------------
@pytest.mark.parametrize("reply", [
    "I'm connecting you now. You won't need to repeat yourself.",
    "I guarantee the review will go smoothly.",
    "We'll process it right away and approve it.",
])
def test_g1_commitments_caught(reply):
    assert any(v.startswith("G1") for v in gates(reply))


def test_g1_exempts_text_quoted_from_facts():
    f = sop_facts(guide__alternative="If you cannot get the full office note immediately, ask the clinic; "
                                      "a human representative should review what other clinical records may be acceptable.")
    reply = "If you cannot get the full office note immediately, ask the clinic; a human representative should review what other clinical records may be acceptable."
    assert not [v for v in gates(reply, facts=f) if v.startswith("G1")]


# --- G2 outcome predictions ----------------------------------------------------------------------
@pytest.mark.parametrize("reply", [
    "Once you send them, your claim will be approved.",
    "It should likely be reimbursed after review.",
    "She will approve it shortly.",
    "You'll get $1,450.00 for this claim.",
])
def test_g2_predictions_caught(reply):
    assert any(v.startswith("G2") for v in gates(reply))


def test_g2_allows_neutral_process_language():
    assert not gates("Once the files are received, the review usually restarts.")


# --- G3 capabilities need their sop/email fact ----------------------------------------------------
@pytest.mark.parametrize("reply,missing", [
    ("I can email a summary to m***@email.com.", "email"),
    ("No email will be sent.", "email status"),
    ("I can only help with insurance questions.", "scope"),
    ("I can connect you with a human representative.", "human-transfer"),
])
def test_g3_capability_without_fact(reply, missing):
    assert any(v.startswith("G3") and missing in v for v in gates(reply, facts=FactSheet()))


def test_g3_capability_with_fact_passes():
    f = sop_facts(email__to_masked="m***@email.com")
    assert not gates("I can email a summary to m***@email.com, or connect you with a human representative.", facts=f)


# --- G4 state contradictions ----------------------------------------------------------------------
def test_g4_verified_caller_told_to_verify():
    v = gates("I'm not able to skip or change our verification and security steps.")
    assert any(x.startswith("G4") for x in v)


def test_g4_unverified_caller_told_verified():
    s = SessionState()
    assert any(x.startswith("G4") for x in gates("Great, you're verified. Your claim is denied.", state=s))


def test_g4_conditional_phrasing_is_fine():
    s = SessionState()
    assert not gates("I'll look at it as soon as you're verified.", state=s)


# --- G5 addressing ------------------------------------------------------------------------------
def test_g5_representative_called_policyholder_name():
    s = verified_state()
    s.memory.caller_role = Slot(value="representative", turn=1)
    s.memory.representative_name = Slot(value="David Chen", turn=1)
    assert any(x.startswith("G5") for x in gates("Thank you, Margaret. I've verified the details.", state=s))
    assert not gates("Thank you, David. I've verified the policyholder's details.", state=s)


# --- G6 scope discipline --------------------------------------------------------------------------
def test_g6_off_topic_turn_offers_human_early():
    v = gates("I can only help with claims. I can connect you with a human representative.",
              actions=["OFF_TOPIC_REFUSAL"])
    assert any(x.startswith("G6") for x in v)


def test_g6_off_topic_turn_starts_answering():
    v = gates("RL stands for reinforcement learning, but I can only help with claims.", actions=["OFF_TOPIC_REFUSAL"])
    assert any("starts answering" in x for x in v)


def test_g6_human_offer_allowed_at_threshold():
    v = gates("I can only help with claims. Would you like me to connect you with a human representative?",
              actions=["OFF_TOPIC_REFUSAL", "OFFER_HUMAN"])
    assert not [x for x in v if x.startswith("G6")]


# --- verifier rule 10 regression (caused 16 template fallbacks in the live eval) -------------------
def test_case_id_as_subject_of_cited_fact_is_supported(repo):
    from app.grounding.verifier import verify_reply
    from app.tools import ToolBox

    s = verified_state()
    s.transcript.append(Message(role="user", content="why denied?", turn=1))
    facts = ToolBox(s, repo).call("get_claim", case_id="CL-2048")
    claims = [{"text": "Claim CL-2048 is denied.", "fact_ids": ["claim.CL-2048.status"]}]
    assert verify_reply("Claim CL-2048 is denied.", claims, facts, s, repo).ok
    wrong = [{"text": "Claim CL-2048 is denied.", "fact_ids": ["schema.net_pay"]}]
    assert not verify_reply("Claim CL-2048 is denied.", wrong, facts, s, repo).ok


# --- G9 amount meaning ---------------------------------------------------------------------------
def claim_amount_facts(case="CL-2048", expected="0.00", allowed="1450.00", net_pay="0.00", net_fee="1450.00"):
    f = sop_facts()
    for key, value in {"expected_reimbursement_amount": expected, "allowed_max_amount": allowed,
                       "net_pay": net_pay, "net_fee": net_fee}.items():
        f.add(f"claim.{case}.{key}", value, "claim_record")
    return f


@pytest.mark.parametrize("reply", [
    "You'll receive $1,450.00 for this claim.",
    "The insurer paid $1450.00 on this claim.",
    "Your payment will be 1450.00.",
    "The maximum allowed amount is $0.00.",
])
def test_g9_amount_misuse_caught(reply):
    assert any(v.startswith("G9") for v in gates(reply, facts=claim_amount_facts()))


@pytest.mark.parametrize("reply", [
    "The maximum allowed amount is $1,450.00, and nothing has been paid so far ($0.00).",
    "The most the insurer pays for a covered service is $1,450.00.",
    "The net pay on record is $0.00 and the expected reimbursement is $0.00.",
    "On record: paid so far $0.00, expected reimbursement $0.00, and the maximum allowed amount is $1450.00.",
])
def test_g9_correct_amount_meaning_passes(reply):
    assert not any(v.startswith("G9") for v in gates(reply, facts=claim_amount_facts()))


def test_g9_open_claim_expected_vs_cap():
    f = claim_amount_facts("CL-2102", expected="3200.00", allowed="3500.00", net_pay="0.00", net_fee="3500.00")
    assert not any(v.startswith("G9") for v in gates(
        "The expected reimbursement is $3,200.00 and the allowed maximum is $3,500.00.", facts=f))
    assert any(v.startswith("G9") for v in gates("You'll get $3,500.00 once it closes.", facts=f))
