"""Behavioural boundary gates, run on every reply next to the token-level grounding checks.

The verifier proves *values* (ids, money, dates, documents) come from facts. These gates cover the
statement types the live evals showed slipping through, each derived from Context.md / RESEARCH.md:

  G1 commitments     - promises about future process ("you won't need to repeat yourself", "guarantee").
                       Air Canada ruling: an invented promise is a liability, not a style issue.
  G2 outcome bait    - predicting decisions the record does not contain ("will be approved", "she will
                       approve", "you'll get $1,450"). Only claim_record facts state outcomes.
  G3 capabilities    - "I can email…", "I can connect you…", "I can only help with…" must be backed by the
                       sop.* / email.* fact for that capability (Sierra: rules are content too).
  G4 state contradiction - telling a verified caller they still need verification, or an unverified caller
                       that they are verified (Context.md: SOP controls the safety gates).
  G5 addressing      - a representative must not be addressed as the policyholder.
  G6 scope discipline - an off-topic refusal must not answer the off-topic question or offer a human before
                       the SOP threshold (Context.md: refuse politely; human only if the caller keeps retrying).
  G7 session context - "you said / I've noted / you mentioned…" must be backed by the chat: any value quoted
                       back must appear in the caller's own messages, and a caller.*/memory fact must exist.
  G8 decision fidelity - the reply must state the outcome the controller decided (e.g. verification failed)
                       and must not describe work the system is not doing ("I'll check them now").
"""

from __future__ import annotations

import re

from ..state import SessionState
from .factsheet import FactSheet

COMMITMENT_PATTERNS = [
    (r"\b(won'?t|will not|don'?t|do not|shouldn'?t|should not|never|wouldn'?t) (need|have) to repeat\b|"
     r"\bno need to repeat\b|\bwithout (having to )?repeat", "promise about the handoff"),
    (r"\bguarantee[ds]?\b|\bI promise\b|\bdefinitely will\b|\bcertainly will\b", "guarantee"),
    (r"\b(right away|immediately|as soon as possible|asap)\b.*\b(approv|pay|process|review)", "speed promise"),
]

OUTCOME_PATTERNS = [
    r"\b(will|should|is going to|are going to|would)\s+(likely\s+|probably\s+)?(be\s+)?"
    r"(approved|paid|reimbursed|overturned|reprocessed|accepted|reversed|covered)\b",
    r"\b(she|he|they|the policyholder)\s+(will|should|is going to)\s+(approve|accept|consent)\b",
    r"\byou('| wi)ll\s+(get|receive|be paid)\b",
]

CAPABILITY_GATES = [
    (r"\bI (can|could|will|'ll) (email|send) (you )?(a |the )?summary\b|\bemail (you )?a summary\b",
     ("email.to_masked", "email.sent_to_masked"), "email capability"),
    (r"\b(connect|transfer) you\b|\bwith a human representative\b",
     ("sop.human_transfer", "transfer.reason", "offer.human_transfer_reason"), "human-transfer capability"),
    (r"\bI can only help with\b|\bonly (able to )?help with\b|\boutside (of )?what I can help\b",
     ("sop.scope",), "scope statement"),
    (r"\bno email (will be|was) sent\b|\bwon'?t send (an |the )?email\b",
     ("email.status",), "email status"),
]

NEEDS_VERIFICATION_PATTERNS = [
    r"\b(need|have) to verify your identity\b", r"\bverify your identity (first|before)\b",
    r"\bbefore I can (look|share|discuss|access)\b", r"\bskip( or change)? (the |our |any )?verification\b",
    r"\buntil (you'?re|you are) verified\b",
]
# Conditional phrasing ("as soon as you're verified") is not a claim of being verified.
CLAIMS_VERIFIED_PATTERNS = [
    r"(?<!as soon as )(?<!once )(?<!until )(?<!when )(?<!after )(?<!if )\byou('?re| are) (now )?verified\b",
    r"\bI('?ve| have) verified you\b",
]


def _in_facts(span: str, facts: FactSheet) -> bool:
    """Text quoted from a fact (e.g. guideline wording) is grounded by definition."""
    norm = " ".join(span.casefold().split())
    return any(norm in " ".join(v.casefold().split()) for v in facts.values())


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2014": " - ", "\u2013": "-"})


def normalize_quotes(text: str) -> str:
    return text.translate(_QUOTES)


CONTEXT_REFERENCE = re.compile(
    r"\b(you (said|mentioned|told me|shared|provided|gave)|as you (said|mentioned)|I'?ve noted|I have noted|"
    r"you'?re calling about|you are calling about|earlier you)\b", re.I)
VALUE_TOKEN = re.compile(r"\b\d[\d/\-.]*\d\b|\b\d\b|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Phrases that must appear when the controller took the decision (any one per action).
REQUIRED_OUTCOME = {
    "VERIFICATION_FAILED": r"(couldn'?t|could not|wasn'?t able to|was not able to|unable to|not able to) verify|"
                           r"(didn'?t|did not|doesn'?t|does not|don'?t) match",
    "VERIFICATION_LOCKED": r"(couldn'?t|could not|wasn'?t able to|unable to|not able to) (be )?(verif|complete)",
    "VERIFIED": r"\bverified\b",
    "EMAIL_SENT": r"\bsent\b",
    "EMAIL_SKIPPED": r"(won'?t|will not|not) (send|be sent)|\bno email\b",
    "TRANSFER_HUMAN": r"\b(connect|connecting|transfer|transferring)\b",
    "CONSENT_PENDING": r"\b(pending|waiting|consent|approv)",
    "OFF_TOPIC_REFUSAL": r"\bonly (able to )?help|can'?t help with that|outside (of )?(what|the)|not able to help with that",
    "CLARIFY_FIELDS": r"\b(again|clarify|restate|re-?enter|full|complete|unclear|couldn'?t read)\b",
}
PENDING_WORK = re.compile(
    r"\b(I'?ll|I will|let me|I'?m going to) (check|verify|look (into|up|over)|review|validate) "
    r"(them|it|that|those|these|your (details|information|info))( now| right now| shortly| in a moment)?\b(?! (once|after|when|as soon))|"
    r"\bone moment\b|\b(checking|verifying) (them|that|those|your details) now\b", re.I)


def check_gates(reply: str, facts: FactSheet, state: SessionState, actions: list[str] | None = None) -> list[str]:
    actions = actions or []
    reply = normalize_quotes(reply)  # live: nano wrote "won’t" (U+2019) and slipped past every ASCII pattern
    text = reply.casefold()
    out: list[str] = []

    for pattern, label in COMMITMENT_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            if not _in_facts(m.group(0), facts):
                out.append(f"G1 commitment not backed by any fact ({label})")

    for pattern in OUTCOME_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            sentence_start = max(text.rfind(".", 0, m.start()), text.rfind("?", 0, m.start()), text.rfind("!", 0, m.start()))
            prefix = text[sentence_start + 1:m.start()]
            if re.search(r"\b(whether|if|don't know|do not know|can't (say|predict|tell)|cannot (say|predict|tell)|"
                         r"not able to (say|predict)|no (information|way to know)|unable to (say|predict))\b", prefix):
                continue  # hedged / negated: "I can't say whether she will approve" is not a prediction
            if not _in_facts(m.group(0), facts):
                out.append(f"G2 predicts an outcome not in the record: '{m.group(0)}'")

    for pattern, fact_ids, label in CAPABILITY_GATES:
        if re.search(pattern, text, re.I) and not any(f in facts for f in fact_ids):
            out.append(f"G3 {label} stated without its sop fact ({' / '.join(fact_ids)})")

    if state.verified and any(re.search(p, text) for p in NEEDS_VERIFICATION_PATTERNS):
        out.append("G4 tells an already-verified caller that verification is still required")
    if not state.verified and any(re.search(p, text) for p in CLAIMS_VERIFIED_PATTERNS) \
            and "VERIFIED" not in actions:
        out.append("G4 tells an unverified caller they are verified")

    role = state.memory.caller_role.value if state.memory.caller_role else None
    if role == "representative" and state.verification.party_id:
        from ..fixtures import get_repo  # local import keeps gates free of repo state otherwise
        holder = get_repo().policyholder(state.verification.party_id)
        first = holder["name"].split()[0].casefold() if holder else None
        rep = (state.memory.representative_name.value if state.memory.representative_name else "") or ""
        if first and first not in rep.casefold() and re.search(
                rf"\b(thank you|thanks|hi|hello|sorry|okay|ok|great)[,!.]?\s+{re.escape(first)}\b", text):
            out.append("G5 addresses the representative by the policyholder's name")

    if "OFF_TOPIC_REFUSAL" in actions and not ({"ANSWER_CASE", "OFFER_HUMAN", "TRANSFER_HUMAN"} & set(actions)):
        if re.search(r"\bhuman representative\b|\bconnect you\b|\btransfer you\b", text):
            out.append("G6 offers a human on an off-topic turn before the SOP threshold")
        if re.search(r"\b(stands for|refers to|is a (type|kind|branch|method)|means that|in short,)\b", text):
            out.append("G6 starts answering the off-topic question")

    # G7: references to the conversation must be backed by the conversation.
    caller_text = " ".join(m.content.casefold() for m in state.transcript if m.role == "user")
    has_context_fact = any(f.source == "caller" for f in facts.facts.values()) or bool(
        state.memory.case_hints or state.memory.intent or state.memory.pii)
    for sentence in re.split(r"(?<=[.!?])\s+", reply):
        if not CONTEXT_REFERENCE.search(sentence):
            continue
        if not has_context_fact:
            out.append("G7 refers to something the caller said, but nothing is in session memory")
        for token in VALUE_TOKEN.findall(sentence):
            if token.casefold() not in caller_text and not _in_facts(token, facts):
                out.append(f"G7 quotes '{token}' as the caller's words, but the caller never said it")

    # G8: say what was decided; don't narrate work that isn't happening.
    for action, pattern in REQUIRED_OUTCOME.items():
        if action in actions and not re.search(pattern, reply, re.I):
            out.append(f"G8 reply does not state the decided outcome ({action})")
    if (m := PENDING_WORK.search(reply)):
        out.append(f"G8 describes work the system is not doing: '{m.group(0)}'")
    return out
