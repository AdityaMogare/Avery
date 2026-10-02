"""LLM code path with a scripted fake model: hallucinations are rejected, regenerated, then replaced."""

from app.llm import to_strict_schema
from app.pipeline import Agent
from app.responder import ResponseDraft
from app.state import SessionState
from app.understanding import HeuristicUnderstander, TurnUnderstanding


class FakeLLM:
    """Understanding via the heuristic; replies from a scripted list."""

    model = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def structured(self, system, messages, schema, name):
        if schema is TurnUnderstanding:
            text = messages[-1]["content"].split("Caller message: ", 1)[-1]
            return HeuristicUnderstander().understand(SessionState(), text)
        self.calls += 1
        return self.replies.pop(0)


def agent_with(replies):
    agent = Agent(api_key=None)
    agent.llm = FakeLLM(replies)
    agent.mode = "llm:fake"
    return agent


DEMO = ("My name is Margaret Chen, DOB 1985-03-15, SSN last four 4472. "
        "I'm calling about my denied healthcare claim from January.")


def test_hallucinated_reply_regenerated_then_accepted():
    bad = ResponseDraft(reply="Claim CL-2048 was denied; you have 30 days to appeal and will get $1,450.00.",
                        claims=[])
    good = ResponseDraft(
        reply="Thanks Margaret, you're verified. Claim CL-2048 was denied because the review file did not include "
              "the pathology report and the treating provider office note.",
        claims=[{"text": "Claim CL-2048 was denied", "fact_ids": ["claim.CL-2048.case_id", "claim.CL-2048.status"]},
                {"text": "reason", "fact_ids": ["claim.CL-2048.denial_reason"]}])
    agent = agent_with([bad, good])
    s = SessionState()
    agent.start(s)
    r = agent.handle(s, DEMO)
    assert r.reply == good.reply and r.verifier["ok"]
    violations = [e for e in s.trace if e.type == "grounding_violation"]
    assert len(violations) == 1
    assert any("30 days" in v for v in violations[0].data["violations"])
    # Known limit: $1,450.00 IS a real fact (allowed_max_amount), so the regex layer accepts the number even
    # though "you will get $1,450" misuses it. Semantic misuse is the LLM judge's job (test_scenarios_llm.py).
    assert not any("1,450.00" in v for v in violations[0].data["violations"])
    assert [e.data["responder"] for e in s.trace if e.type == "response"] == ["llm_regenerated"]


def test_persistent_hallucination_falls_back_to_template():
    bad = ResponseDraft(reply="Your claim CL-2048 will be approved within 2 business days.", claims=[])
    agent = agent_with([bad, bad])
    s = SessionState()
    agent.start(s)
    r = agent.handle(s, DEMO)
    assert "approved within" not in r.reply and r.verifier["ok"]
    assert [e.data["responder"] for e in s.trace if e.type == "response"] == ["template_fallback"]


def test_pre_verification_leak_is_blocked():
    leak = ResponseDraft(reply="I see your claim CL-2048 is denied for a missing pathology report. "
                               "Can you give me your date of birth?", claims=[])
    agent = agent_with([leak, leak])
    s = SessionState()
    agent.start(s)
    r = agent.handle(s, "Hi, I'm calling about my denied healthcare claim from January.")
    assert "CL-2048" not in r.reply and "pathology" not in r.reply


def test_strict_schema_shape():
    for model in (TurnUnderstanding, ResponseDraft):
        schema = to_strict_schema(model)

        def walk(node):
            if isinstance(node, dict):
                assert "default" not in node
                if node.get("type") == "object" and "properties" in node:
                    assert node["additionalProperties"] is False
                    assert set(node["required"]) == set(node["properties"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(schema)
