"""Session-context guardrails: extracted values and quoted context must come from the actual chat.

Origin: UI session where "my dob is 12/03/200" was extracted as 2000-12-03 (invented year, burned an
attempt) and the reply said "I've noted the details you shared, and I'll check them now" while the
controller had already decided VERIFICATION_FAILED.
"""

import pytest

from app.grounding.extraction_guard import ground_understanding
from app.grounding.factsheet import FactSheet
from app.grounding.gates import check_gates
from app.state import Message, SessionState
from app.understanding import TurnUnderstanding


# --- extraction guard ----------------------------------------------------------------------------
def test_invented_year_is_rejected():
    msg = "My name is marget , my dob is 12/03/200 and my last digits are 4421"
    res = ground_understanding(TurnUnderstanding(full_name="Marget", dob="2000-12-03", id_last4="4421"), msg)
    assert res.understanding.dob is None and res.rejected["dob"] == "12/03/200"
    assert res.understanding.id_last4 == "4421" and res.understanding.full_name == "Marget"


def test_model_spelling_correction_is_reverted_to_callers_words():
    msg = "My name is Margret Chen, DOB 1985-03-15, SSN last four 4472"
    res = ground_understanding(TurnUnderstanding(full_name="Margaret Chen", dob="1985-03-15", id_last4="4472"), msg)
    assert res.understanding.full_name == "Margret Chen" and res.corrected == {"name": "Margret Chen"}


@pytest.mark.parametrize("field,value", [("id_last4", "9999"), ("phone", "6505550000"),
                                         ("email", "someone@else.com"), ("full_name", "Ava Lopez")])
def test_values_not_in_message_are_dropped(field, value):
    msg = "Hi, I'm calling about my claim. My SSN last four is 4472."
    res = ground_understanding(TurnUnderstanding(**{field: value}), msg)
    assert getattr(res.understanding, field) is None


@pytest.mark.parametrize("msg,dob", [
    ("DOB is March 15, 1985", "1985-03-15"),
    ("born 03/15/1985", "1985-03-15"),
    ("dob 15th March 1985", "1985-03-15"),
])
def test_valid_dob_formats_are_kept(msg, dob):
    assert ground_understanding(TurnUnderstanding(dob=dob), msg).understanding.dob == dob


def test_two_digit_year_is_asked_not_guessed():
    res = ground_understanding(TurnUnderstanding(dob="1985-03-15"), "dob 3/15/85")
    assert res.understanding.dob is None


def test_malformed_dob_does_not_burn_an_attempt(offline_agent):
    s = SessionState()
    offline_agent.start(s)
    # Heuristic path: unparseable date is never extracted; 2 grounded fields -> ask, no failed attempt.
    offline_agent.handle(s, "My name is Margaret Chen, my dob is 12/03/200 and my SSN last four is 4472")
    assert s.verification.failed_attempts == 0


# --- G7 session-context references -----------------------------------------------------------------
def state_with(*user_msgs) -> SessionState:
    s = SessionState()
    for i, m in enumerate(user_msgs, 1):
        s.transcript.append(Message(role="user", content=m, turn=i))
    return s


def test_g7_quoting_values_the_caller_never_said():
    s = state_with("my dob is 12/03/200")
    v = check_gates("You said your date of birth is 2000-12-03.", FactSheet(), s)
    assert any("G7" in x and "2000-12-03" in x for x in v)


def test_g7_quoting_callers_actual_words_is_fine():
    s = state_with("my dob is 12/03/200")
    s.memory.pii["dob"] = __import__("app.state", fromlist=["Slot"]).Slot(value="12/03/200", turn=1)
    assert not [x for x in check_gates("You said your date of birth is 12/03/200.", FactSheet(), s) if "G7" in x]


def test_g7_reference_with_empty_memory():
    s = state_with("hello")
    v = check_gates("As you mentioned, your claim was denied.", FactSheet(), s)
    assert any("nothing is in session memory" in x for x in v)


# --- G8 decision fidelity ------------------------------------------------------------------------
def test_g8_screenshot_reply_is_rejected():
    s = state_with("My name is marget , my dob is 12/03/200 and my last digits are 4421")
    reply = "Thanks. I've noted the details you shared, and I'll check them now."
    v = check_gates(reply, FactSheet(), s, actions=["VERIFICATION_FAILED"])
    assert any("decided outcome (VERIFICATION_FAILED)" in x for x in v)
    assert any("not doing" in x for x in v)


def test_g8_correct_failure_reply_passes():
    s = state_with("My name is Margaret Chen, DOB 1990-01-01, SSN last four 1111")
    reply = "I wasn't able to verify your identity with those details. Please share at least 3 details again."
    assert not [x for x in check_gates(reply, FactSheet(), s, actions=["VERIFICATION_FAILED"]) if "G8" in x]


def test_g8_future_conditional_look_is_not_pending_work():
    s = state_with("calling about my denied claim")
    assert not [x for x in check_gates("I'll look into it once you're verified.", FactSheet(), s) if "G8" in x]


def test_rep_own_name_not_used_as_policyholder_name():
    msg = "I'm John Smith calling for my wife Margaret Chen. DOB 1985-03-15, SSN last four 4472."
    und = TurnUnderstanding(full_name="John Smith", representative_name="John Smith", caller_role="representative")
    assert ground_understanding(und, msg).understanding.full_name == "Margaret Chen"


def test_g1_catches_shouldnt_have_to_repeat():
    from app.grounding.gates import check_gates as cg
    v = cg("I'm connecting you now. You shouldn't have to repeat yourself.", FactSheet(), SessionState())
    assert any(x.startswith("G1") for x in v)


def test_gates_handle_typographic_apostrophes():
    from app.grounding.gates import check_gates as cg
    v = cg("I’m connecting you now, and you won’t have to repeat yourself.", FactSheet(), SessionState())
    assert any(x.startswith("G1") for x in v)


def test_backfill_recovers_values_the_model_dropped(offline_agent):
    from app.pipeline import Agent

    class DroppingLLM:
        model = "fake"

        def structured(self, system, messages, schema, name):
            if schema is TurnUnderstanding:  # model "forgets" DOB and SSN digits that are in the message
                return TurnUnderstanding(full_name="Margaret Chen", phone="6505212836")
            raise AssertionError("responder not needed")

    agent = Agent(api_key=None)
    agent.llm, agent.mode = DroppingLLM(), "llm:fake"
    agent._respond_verified = lambda state, decision, message, errors, *_: (  # skip responder for this test
        agent.template.respond(state, decision, message),
        type("C", (), {"ok": True, "violations": [], "as_dict": lambda self: {"ok": True}})(), "template")
    s = SessionState()
    agent.start(s)
    agent.handle(s, "I'm Margaret Chen. DOB 1985-03-15, SSN last four 4472, phone 650-521-2836.")
    assert s.verified and any(e.type == "extraction_backfill" for e in s.trace)


def test_g2_hedged_prediction_is_allowed_but_plain_prediction_is_not():
    from app.grounding.gates import check_gates as cg
    s = SessionState()
    assert not [x for x in cg("I can't say whether she will approve it.", FactSheet(), s) if x.startswith("G2")]
    assert [x for x in cg("Don't worry, she will approve it.", FactSheet(), s) if x.startswith("G2")]


def test_claim_hints_must_be_in_the_message():
    und = TurnUnderstanding(case_status="open", case_type="auto", case_month=2)
    res = ground_understanding(und, "How long does it take after I submit?")
    u = res.understanding
    assert u.case_status is None and u.case_type is None and u.case_month is None


def test_null_placeholder_strings_are_treated_as_not_stated():
    """Live (gpt-5.4-nano via OpenRouter): after verification, "I already told you who I am... tell me why my
    claim was denied" came back with case_id/policy_number/phone/representative_name = "null". The agent said
    it couldn't find a claim matching "null" and overwrote the remembered policy number."""
    from app.pipeline import Agent
    from app.understanding import HeuristicUnderstander

    nulls = {"full_name": "null", "dob": "null", "phone": "null", "email": "None", "id_last4": "n/a",
             "policy_number": "null", "representative_name": "null", "representative_relationship": "null",
             "case_id": "null", "case_type": "null", "case_status": "null", "caller_role": "null", "intent": "null",
             "question": "Why was my claim denied?", "caller_notes": ["null"], "emotion": "frustrated"}

    class NullStringLLM:
        model = "fake"
        turn = 0

        def structured(self, system, messages, schema, name):
            assert schema is TurnUnderstanding
            self.turn += 1
            if self.turn == 1:
                return HeuristicUnderstander().understand(SessionState(), messages[-1]["content"].split(
                    "LATEST CALLER MESSAGE (extract from this only):\n", 1)[-1])
            return TurnUnderstanding.model_validate(nulls)  # what LLMClient does with the parsed JSON

    agent = Agent(api_key=None)
    agent.llm, agent.mode = NullStringLLM(), "llm:fake"
    agent._respond_verified = lambda state, decision, message, errors, *_: (
        agent.template.respond(state, decision, message),
        type("C", (), {"ok": True, "violations": [], "as_dict": lambda self: {"ok": True}})(), "template")
    s = SessionState()
    agent.start(s)
    agent.handle(s, "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied "
                    "healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.")
    assert s.verified and s.selected_case_id == "CL-2048"
    result = agent.handle(s, "I already told you who I am. This is ridiculous. Just tell me why my claim was denied.")
    assert "NO_MATCHING_CASE" not in result.actions
    assert s.selected_case_id == "CL-2048"
    assert s.memory.policy_number.value == "POL-9921"
    assert s.memory.representative_name is None and "phone" not in s.memory.pii
    assert "null" not in result.reply.casefold()


def test_null_placeholders_parse_to_defaults():
    u = TurnUnderstanding.model_validate({"case_id": "NULL", "case_type": "none", "phone": " n/a ",
                                          "caller_notes": ["null", "has a hospital bill"], "followup_topics": []})
    assert u.case_id is None and u.case_type is None and u.phone is None
    assert u.caller_notes == ["has a hospital bill"]


@pytest.mark.parametrize("field", ["phone", "id_last4", "policy_number", "case_id"])
def test_digitless_values_are_not_grounded(field):
    und = TurnUnderstanding(**{field: "unknown-value"})
    out = ground_understanding(und, "Just tell me why my claim was denied. My number is 6505212836.")
    assert getattr(out.understanding, field) is None


@pytest.mark.parametrize("message,explains", [
    ("I already told you who I am. This is ridiculous. Just tell me why my claim was denied.", True),
    ("Why do you need all that?", True),
    ("Just tell me what you need from me.", False),  # an ordinary request, not pushback
])
def test_refusal_backstop_when_model_misses_it(message, explains):
    """Live (gpt-5.4-nano): the bonus example's pushback came back refuses_verification=false, so the agent
    never explained why verification is required."""
    from app.pipeline import Agent

    class MissesRefusal:
        model = "fake"

        def structured(self, system, messages, schema, name):
            assert schema is TurnUnderstanding
            text = messages[-1]["content"].split("LATEST CALLER MESSAGE (extract from this only):\n", 1)[-1]
            return TurnUnderstanding(full_name="Margaret Chen" if "Margaret" in text else None,
                                     emotion="frustrated" if "ridiculous" in text else "neutral")

    agent = Agent(api_key=None)
    agent.llm, agent.mode = MissesRefusal(), "llm:fake"
    agent._respond_verified = lambda state, decision, message, errors, *_: (
        agent.template.respond(state, decision, message),
        type("C", (), {"ok": True, "violations": [], "as_dict": lambda self: {"ok": True}})(), "template")
    s = SessionState()
    agent.start(s)
    agent.handle(s, "My name is Margaret Chen.")
    result = agent.handle(s, message)
    assert ("EXPLAIN_VERIFICATION" in result.actions) is explains
    assert not s.verified


def test_off_topic_message_drops_invented_intent_and_offer_answer():
    """Live (gpt-5.4-nano via OpenRouter): "What is RL?" came back is_off_topic=true but also with
    intent=general_claim_question and affirmation="no", which made the agent answer the claim too."""
    und = TurnUnderstanding(is_off_topic=True, intent="general_claim_question", affirmation="no",
                            email_choice="skip", question="What is RL?")
    out = ground_understanding(und, "What is RL?").understanding
    assert out.intent is None and out.affirmation is None and out.email_choice is None
    # A mixed message keeps what its words support.
    mixed = TurnUnderstanding(is_off_topic=True, intent="denial_question", affirmation="no")
    kept = ground_understanding(mixed, "No. What is RL? And why was my claim denied?").understanding
    assert kept.intent == "denial_question" and kept.affirmation == "no"


def test_off_topic_after_verification_with_invented_intent_is_a_plain_refusal(offline_agent):
    from app.pipeline import Agent
    from app.understanding import HeuristicUnderstander

    class InventsIntent:
        model = "fake"

        def structured(self, system, messages, schema, name):
            text = messages[-1]["content"].split("LATEST CALLER MESSAGE (extract from this only):\n", 1)[-1]
            if text == "What is RL?":
                return TurnUnderstanding(is_off_topic=True, intent="general_claim_question", affirmation="no",
                                         case_type="healthcare", question="What is RL?")
            return HeuristicUnderstander().understand(SessionState(), text)

    agent = Agent(api_key=None)
    agent.llm, agent.mode = InventsIntent(), "llm:fake"
    agent._respond_verified = lambda state, decision, message, errors, *_: (
        agent.template.respond(state, decision, message),
        type("C", (), {"ok": True, "violations": [], "as_dict": lambda self: {"ok": True}})(), "template")
    s = SessionState()
    agent.start(s)
    agent.handle(s, "My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472. I'm calling about my denied "
                    "healthcare claim from January.")
    result = agent.handle(s, "What is RL?")
    assert "OFF_TOPIC_REFUSAL" in result.actions and "ANSWER_CASE" not in result.actions
    assert s.selected_case_id == "CL-2048"


def test_disambiguation_reply_must_offer_every_candidate(offline_agent):
    """Live (gpt-5.4-nano): "my closed claim" matched CL-2011 and CL-1899, but the reply offered CL-2011 and
    CL-2048 (the stale "healthcare" hint). The verifier now rejects it, and the template lists both."""
    from app.grounding.verifier import verify_reply

    s = SessionState()
    offline_agent.start(s)
    offline_agent.handle(s, "My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472. I'm calling about my "
                            "denied healthcare claim from January.")
    result = offline_agent.handle(s, "Actually I wanted to ask about my closed claim.")
    assert "DISAMBIGUATE" in result.actions and sorted(s.candidate_case_ids) == ["CL-1899", "CL-2011"]
    hint = next(f["value"] for f in result.facts if f["id"] == "caller.case_hint")
    assert "healthcare" not in hint and "January" not in hint  # only what the caller said this turn
    from app.grounding.factsheet import FactSheet
    facts = FactSheet()
    for f in result.facts:
        facts.add(f["id"], f["value"], f["source"])
    bad = ("A few claims could match a closed healthcare claim: CL-2011 (healthcare, closed) and CL-2048 "
           "(healthcare, denied). Which one would you like to discuss?")
    check = verify_reply(bad, [], facts, s, offline_agent.repo, result.actions)
    assert any("leaves out candidate claim(s) CL-1899" in v for v in check.violations)
    assert "CL-1899" in result.reply and "CL-2011" in result.reply


def test_intent_that_narrows_nothing_asks_which_claim(offline_agent):
    """Live (gpt-5.4-nano via OpenRouter): with no claim described, an intent tied all four claims and the agent
    said "a few could match" over all of them. With nothing narrowed, it asks which claim instead."""
    s = SessionState()
    offline_agent.start(s)
    offline_agent.handle(s, "My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472.")
    assert s.verified
    s.memory.case_hints = {}
    from app.state import Slot
    s.memory.intent = Slot(value="status_inquiry", turn=s.turn)
    result = offline_agent.handle(s, "Okay.")
    assert "ASK_INTENT" in result.actions and "DISAMBIGUATE" not in result.actions
    assert len(s.candidate_case_ids) == 4
