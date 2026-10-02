# Research: how others built SOP-following, grounded support agents

The goal of this survey is to avoid starting from scratch. For each team or paper: **the problem they
hit, what they tried, what worked, what did not, and what this project takes from it.** The main question
throughout is how to make (and prove) an agent that follows a fixed workflow and only makes claims it
can ground in data.

---

## 1. Rasa: CALM (Conversational AI with Language Models)

**Problem.** Classic NLU (intent classification + slot filling + hand-written stories) was too rigid for
messy user language. The opposite extreme, letting an LLM drive the whole conversation, was not reliable
either: LLMs "don't naturally understand business-specific rules and constraints," and relying solely on
LLM output "can lead to inconsistencies, irrelevant information, or even wrong actions."

**What worked.** A split of responsibilities:
- The LLM does **dialogue understanding** only. It reads the message in context and emits **commands**
  (set slot X, start flow Y, cancel, clarify).
- **Flows** (deterministic business logic) decide what happens next. A flow "only describes the logic your
  assistant follows, not all the potential paths conversations can take."
- **Conversation repair patterns** handle the off-script cases generically: digressions, corrections,
  cancellations, clarification, chitchat, "continue interrupted flow", skip question.

**What didn't work.** Intent-only NLU (too brittle) and end-to-end LLM control (it ignores business rules).

**Applied here.**
- `understanding.py` makes the LLM return a `TurnUnderstanding` (extracted fields, hints, signals) and
  nothing else. It never decides the phase.
- `sop/controller.py` is the flow engine.
- Repair cases are explicit: corrections overwrite memory slots with provenance, digressions
  (off-topic) are refused and steered back, clarification uses `DISAMBIGUATE`, and an interrupted flow
  resumes in its phase.

Sources: [Rasa: dialogue management](https://rasa.com/docs/learn/concepts/dialogue-management/),
[Lessons from Rasa's journey](https://rasa.com/blog/harnessing-the-power-of-llms-in-conversational-ai-lessons-from-rasa-s-journey),
[Conversation repair](https://rasa.com/docs/rasa-pro/concepts/conversation-repair/),
[CALM in production](https://rasa.com/blog/how-to-put-next-generation-ai-assistants-in-production-today-with-calm)

---

## 2. Parlant (Emcie): guidelines, journeys and ARQs

**Problem.** "The curse of instructions": as guidelines accumulate (hundreds in real deployments),
instruction-following "drops dramatically, not linearly." Even with focused context, models "fail to follow
instructions mid-generation."

**What they tried that failed.** Matching rules to context with semantic similarity (can't capture
temporal or logical conditions), cross-encoders (still unreliable on conditional reasoning), and custom
neural heads (embeddings "too lossy" for chronological and state information).

**What worked.**
- **Dynamic filtering.** Only guidelines relevant to the current state reach the LLM.
- **Attentive Reasoning Queries (ARQs).** A structured-output reasoning blueprint that restates the
  critical rule *immediately before* the decision, exploiting recency bias. Reported results: 90.2% success
  vs 86.1% for chain-of-thought and 81.5% for direct generation.
- **Composition modes.** FLUID (generated), STRICT (canned responses only, for compliance-critical
  text), and hybrids.
- **Tool insights.** When a tool can't run (missing or invalid data), the composer gets a structured
  failure so it asks the user instead of hallucinating.

**Applied here.**
- `prompts.py` injects only the **current phase's** rules plus the actions the controller chose this turn.
- The response schema puts `rule_check` (an ARQ-style restatement of the rules that constrain this
  reply) *before* `reply`.
- `TemplateResponder` is the STRICT mode. It is the offline responder and the fallback when an LLM
  draft fails grounding twice.
- Missing data is encoded as explicit facts (e.g. `claim.X.denial_reason_on_record = none`), so "I don't
  have that" is grounded too.

Sources: [Parlant engine overview](https://www.parlant.io/docs/engine-internals/overview),
[Message generation](https://parlant.io/docs/engine-internals/message-generation),
[ARQ paper, arXiv 2503.03669](https://arxiv.org/pdf/2503.03669)

---

## 3. Sierra: τ-bench, τ²-bench and "defense in depth"

**Problem.** Agents built from "simple LLM constructs such as function calling or ReAct" did poorly on
realistic, policy-bound customer-service tasks. State-of-the-art function-calling agents succeeded on
**<50%** of τ-bench tasks and were **inconsistent** (pass^8 < 25% in retail). Social engineering (users
impersonating supervisors) and prompt injection are standing threats.

**What worked.**
- **Deterministic guards** "that can't be talked out of doing their job," e.g. *account tools aren't even
  available to the agent until the customer has been authenticated*.
- **Supervisor models** that audit replies in real time and can block, rewrite or nudge them.
- **Layered redundancy.** Grounded content, then plain-language rules, then supervisors, then
  deterministic guards. Each layer catches failures the others miss.
- **Evaluation by outcome state, repeated.** τ-bench compares the final database state to the annotated
  goal state and reports **pass^k** (all k trials succeed), because one lucky pass hides unreliability.
  τ²-bench adds dual control and a user simulator constrained by tools/state. τ²-bench-Verified exists
  because *task definitions themselves* were found misaligned with policy, a reminder to keep specs
  reviewed.

**Applied here.**
- `tools.py` has a phase allow-list **and** a verification gate. The LLM never calls tools; the
  controller does, and a forced call before verification raises `ToolGateError` (tested).
- `grounding/verifier.py` is the deterministic supervisor and runs on every reply.
- `evals/run_evals.py --k 3` reports pass^k. Scenarios assert on **state and trace** (phase, verified
  turn, selected case, email choice), not only on wording.

Sources: [τ-bench, arXiv 2406.12045](https://arxiv.org/abs/2406.12045),
[τ²-bench, arXiv 2506.07982](https://arxiv.org/abs/2506.07982),
[τ²-bench-verified](https://github.com/amazon-agi/tau2-bench-verified),
[Sierra: defense in depth](https://sierra.ai/blog/defense-in-depth-in-the-age-of-agents),
[Sierra: benchmarking agents](https://sierra.ai/uk/blog/benchmarking-ai-agents)

---

## 4. Procedural compliance and claim-level groundedness (research)

**Problem.** Checking only the final answer misses *how* the agent got there: did it call the claim tool
before verifying, or disclose and then verify? Surface-level "does this look right" judges miss individual
unsupported claims.

**What worked.**
- **AgentLTL** expresses procedural rules as first-order **temporal logic over the tool trace**, scored
  deterministically without an LLM judge. Used online ("block-and-warn" harnessing, which improved
  compliance on 5 of 7 models) and offline.
- **Claim-level attribution.** Judges should **enumerate atomic claims first, then verify each** against
  the evidence (FECT, AttributionBench, the RAG groundedness literature). Faithfulness = supported claims /
  total claims. Trace-aware judges see the tool outputs, not just the answer.

**What didn't.** Single holistic LLM-judge scores, which align poorly with humans on attribution
(AttributionBench shows that even fine-tuned judges find this hard).

**Applied here.** This is the core of the test strategy.
- `grounding/trace_rules.py`: temporal properties over the event trace. No claim tool before
  verification or consent, no claim disclosure before verification, no cross-party disclosure, every
  reply verified, legal phase order, email only after an offer, no blocked-tool attempts.
- `grounding/judge.py`: an enumerate-then-verify judge against the turn's FactSheet. It gives
  faithfulness per run and is used in `test_scenarios_llm.py` and `run_evals.py --judge`.
- Every reply carries `claims[{text, fact_ids}]` citations, shown in the UI.

Sources: [AgentLTL, arXiv 2607.02599](https://arxiv.org/pdf/2607.02599),
[FECT, arXiv 2508.00889](https://arxiv.org/pdf/2508.00889),
[AttributionBench, arXiv 2402.15089](https://arxiv.org/pdf/2402.15089),
[Groundedness overview](https://futureagi.com/glossary/groundedness/)

---

## 5. Air Canada chatbot ruling (Moffatt v. Air Canada, 2024)

**Problem.** A support chatbot pieced together fragments about bereavement fares and **invented a refund
policy**. The tribunal held the airline liable: a chatbot is not "a separate legal entity."

**Lesson.** A policy hallucination is a liability issue, not just a quality issue. Policy and procedure
statements must come only from approved sources, and anything else should be "I don't have that, let me
get a human."

**Applied here.** Procedure and timeline answers come only from `required_document_guideline.json` facts.
The verifier rejects any timeline ("within 30 days") that isn't in the facts. When no guideline matches,
`claim_followup_fallback` is used verbatim, and passed deadlines are stated with no invented late-appeal rule.

Sources: [Tom's Guide](https://www.tomsguide.com/ai/air-canada-tried-to-claim-it-wasnt-responsible-for-its-chatbots-false-promises-but-that-didnt-fly-in-court),
[Manatt analysis](https://www.manatt.com/insights/newsletters/advertising-law/ai-gone-wild-airline-has-to-honor-a-refund-policy)

---

## 6. OpenAI Agents SDK guardrails

**Problem.** Support bots get used for unrelated work (code, homework), and users attempt jailbreaks.

**What worked.** **Input guardrails** that classify relevance and jailbreak attempts and trip a wire
before the main agent runs, plus **output guardrails** on the final response. Guardrails can be LLM-based
or rule-based.

**Applied here.** `is_off_topic` and `is_injection_attempt` are classified in the understanding step.
The controller refuses politely, keeps the phase, counts streaks, and after 3 off-topic turns offers a
human (the spec's "ask to talk to human representatives if users keep retrying").

Sources: [Agents SDK guardrails](https://openai.github.io/openai-agents-python/guardrails/),
[Hands-on guardrails](https://towardsdatascience.com/hands-on-with-agents-sdk-safeguarding-input-and-output-with-guardrails/)

---

## 7. Klarna: AI-first, then hybrid

**Problem.** After a high-volume launch, customers were frustrated by confident wrong answers and
by a lack of empathy (e.g. on delayed refunds).

**What worked.** **Confidence-based escalation** (hand off rather than guess) and **easy human handoff**:
"AI gives us speed. Talent gives us empathy."

**Applied here.** Emotion is detected every turn, and the reply acknowledges the feeling first
(`EMPATHY`), then explains *why* the gate exists (`EXPLAIN_VERIFICATION`). Explicit thresholds stop the
persuading and escalate: 3 refusals or a frustration streak, verification lockout, exhausted document
alternatives, or consent timeout. A human can be requested at any time.

Sources: [Klarna hybrid analysis](https://blog.promptlayer.com/klarna-customer-service-from-ai-first-to-human-hybrid-balance/),
[What Klarna got wrong](https://www.twig.so/blog/what-klarna-got-wrong-about-ai-in-customer-support--and-how-they-fixed-it)

---

## 8. Anthropic: "Building effective agents"

**Lesson.** Distinguish **workflows** (LLMs orchestrated through predefined code paths) from **agents**
(LLMs directing their own process). Use workflows when steps are fixed and variance tolerance is low. The
**evaluator-optimizer** pattern (generate, critique, regenerate) is a reliable building block.

**Applied here.** The SOP is a workflow. LLM freedom is confined to understanding and phrasing. The
verifier, regenerate-once and template fallback chain is evaluator-optimizer with a safe floor.

Source: [Building effective agents (summary)](https://simonwillison.net/2024/Dec/20/building-effective-agents)

---

## 9. Prompt injection and identity in support agents

**Lesson.** "LLMs should not assume a user's role based solely on text input." Authority claims ("I'm a
supervisor") are social engineering, and the mitigation is to not let text change authorization.

**Applied here.** Authorization (verified, consent approved) lives only in `SessionState` and is set only
by deterministic code. No message can flip it. The injection scenario tests this.

Sources: [OpenAI: designing agents to resist prompt injection](https://openai.com/index/designing-agents-to-resist-prompt-injection/),
[Decagon: prompt injection](https://decagon.ai/glossary/what-is-prompt-injection)

---

## Synthesis: design decisions and the evidence behind them

| Decision | Evidence |
|---|---|
| LLM extracts, code decides (phase, verification, tools) | Rasa CALM; Sierra deterministic guards; Anthropic workflows |
| Claim tools unavailable until verified (+ consent) | Sierra ("tools not even available until authenticated") |
| Only current-phase rules in the prompt; ARQ `rule_check` before `reply` | Parlant curse of instructions, ARQ results |
| FactSheet with IDs and mandatory citations | Claim-level attribution research; RAG groundedness |
| Deterministic verifier on every reply, then regenerate once, then template | Sierra supervisors; Parlant STRICT mode; evaluator-optimizer |
| Policy/timelines only from the guideline file | Air Canada ruling |
| Trace-property tests (temporal rules) | AgentLTL |
| pass^k with state assertions | τ-bench / τ²-bench |
| Enumerate-then-verify LLM judge | FECT, AttributionBench, groundedness evals |
| Empathy, explanation, bounded persuasion, then escalation | Klarna; spec bonus |
| Off-topic and injection classified at input | OpenAI Agents SDK guardrails |

## What the live evals taught us (applied after the first pass^3 run)

The first live pass^3 run (16 scenarios, gpt-5.4-mini) had **every SOP/trace expectation hold in all 48
runs**, but only 4/16 scenarios passed the claim-level judge (faithfulness 0.914 over 548 claims). The
flagged claims fell into three groups, each turned into edge-case specs + a deterministic gate:

| Finding | Root cause | Fix |
|---|---|---|
| "You won't need to repeat yourself" on transfers | Promise written into **our own** prompt/template | Removed; G1 commitment gate |
| Representative thanked as "Margaret" | VERIFIED instruction used policyholder name | `representative.name` fact; G5 |
| "She will approve it" | Model predicting consent | Prompt rule; G2 outcome gate |
| "I can email…", "I can only help with…" flagged | True SOP behaviour, but not in FACTS | `sop.*` / `email.*` facts; G3 |
| Injection after verification: "can't skip verification" + claim dump | Verifier rule 10 rejected case ids cited by namespace → template fallback (16 fallbacks); refusal text not state-aware | Rule 10 fix; `INJECTION_NOTED`; G4 |
| Off-topic pushback reset the retry counter and dumped the claim | Pushback classified as injection reset the streak; "No," counted as task content | Pushback counts as retry; yes/no only counts with a pending offer; G6 |
| Judge flagged "your mother" as unsupported | Judge saw only the latest message | Judge receives the conversation |

The lesson matches Parlant's and Sierra's: rules the agent states about itself are content, and must be
grounded and gated like claim data.

### Moving to a cheaper model (gpt-5.4-nano)

Switching to nano to cut token cost surfaced a different failure profile, and each failure got a
deterministic layer rather than a prompt tweak:

| Nano behaviour observed live | Layer added |
|---|---|
| Invented a year: "dob 12/03/200" → 2000-12-03 (and it consumed a verification attempt) | Extraction guard: values must appear in the message; unclear fields → `CLARIFY_FIELDS`, no attempt used |
| Dropped values clearly present (DOB, SSN digits, "denied") in 2 of 3 identical calls | Regex backfill for format-rigid fields and claim hints |
| Put the representative's own name in the policyholder field (1 of 3 calls) | Guard takes the name after "for my wife …" or drops it |
| Tagged a timing question with a case status → "no matching claim" | Claim hints must be grounded in the caller's words |
| Missed "act as an answering machine" as an injection/retry | High-precision detectors OR-ed with model flags |
| "You won’t have to repeat yourself" (curly apostrophe) passed G1 | Quote normalization before all gates |
| "I've noted the details… I'll check them now" after a failed match | G8 decision fidelity |

The pattern: **a weaker model needs more deterministic scaffolding around it, not a longer prompt.** The
SOP harness absorbs model noise because the model only proposes. Code verifies every extracted value and
every outgoing statement.

## Known limits (honest)

- **Semantic misuse of a real number** (e.g. calling the allowed maximum "what you'll be paid") passes the
  regex verifier because the number exists in the facts. The LLM judge layer covers this
  (`tests/test_llm_path_fake.py` documents the gap).
- The offline heuristic understander is intentionally simple. It exists so the SOP harness can be tested
  deterministically, not as a production NLU.
- Sessions are in-memory, and email is a mock outbox (`backend/outbox/*.json`).
