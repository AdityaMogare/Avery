"""Calibrate the LLM groundedness judge against labelled replies.

Each row in judge_labels.jsonl is a reply to a caller question about one of P9's claims, labelled
`grounded` (every factual claim is in the facts) or `ungrounded` (at least one invented, embellished or
contradicted claim). The judge sees the same FactSheet the agent would (claim record + guideline + SOP
facts); its reply-level verdict is `ungrounded` if any atomic claim is unsupported or contradicted.

Usage (from apps/insurance_claims/backend):
    LLM_API_KEY=... python -m evals.calibrate_judge [--runs 3]
Writes evals/judge_calibration.md and .json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

os.environ.setdefault("OUTBOX_DIR", tempfile.mkdtemp(prefix="sop-cal-outbox-"))
os.environ.setdefault("AGENT_TODAY", "2026-10-01")

from app import config  # noqa: E402
from app.fixtures import get_repo  # noqa: E402
from app.grounding.factsheet import FactSheet  # noqa: E402
from app.grounding.judge import judge_reply  # noqa: E402
from app.llm import USAGE_SINK, LLMClient, LLMError, summarize_usage  # noqa: E402
from app.state import Phase, SessionState  # noqa: E402
from app.tools import ToolBox  # noqa: E402

OUT = Path(__file__).parent
TOPICS = ["processing_time_after_submission", "submission_method", "file_format_requirements", "submission_timing"]


def facts_for(case_id: str) -> FactSheet:
    """The facts the agent would hold for this claim after verification (P9)."""
    s = SessionState(phase=Phase.PROCESS_CASE)
    s.verification.status, s.verification.party_id = "verified", "P9"
    s.selected_case_id = case_id
    tools = ToolBox(s, get_repo())
    f = tools.call("get_claim", case_id=case_id)
    f.merge(tools.call("get_document_guidance", case_id=case_id, topics=TOPICS))
    f.add("sop.human_transfer", "a human representative can be connected at any time on request", "session")
    return f


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    labels = {x for p in pairs for x in p}
    human, judge = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(human[x] * judge[x] for x in labels) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1, help="judge each row this many times (majority vote kept)")
    args = ap.parse_args()
    key = config.env_api_key()
    if not key:
        print("An LLM API key is required (OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY or LLM_API_KEY)", file=sys.stderr)
        return 2
    judge = LLMClient(key, config.LLM_JUDGE_MODEL)
    rows = [json.loads(line) for line in (OUT / "judge_labels.jsonl").read_text().splitlines() if line.strip()]
    cache = {c: facts_for(c) for c in {r["case"] for r in rows}}
    calls: list[dict] = []
    token = USAGE_SINK.set(calls)
    results = []
    try:
        for row in rows:
            votes, flagged = [], []
            for _ in range(args.runs):
                try:
                    j = judge_reply(judge, row["reply"], cache[row["case"]], row["caller"])
                except LLMError as exc:
                    votes.append("error")
                    flagged.append(str(exc))
                    continue
                bad = [c for c in j.factual if c.verdict in ("unsupported", "contradicted")]
                votes.append("ungrounded" if bad else "grounded")
                flagged.extend(f"{c.verdict}: {c.claim}" for c in bad)
            verdict = Counter(v for v in votes if v != "error").most_common(1)
            verdict = verdict[0][0] if verdict else "error"
            results.append({**row, "judge": verdict, "votes": votes, "flagged": sorted(set(flagged))})
            print(f"{'OK ' if verdict == row['label'] else 'XX '} {row['id']} human={row['label']} judge={verdict}",
                  flush=True)
    finally:
        USAGE_SINK.reset(token)

    scored = [r for r in results if r["judge"] != "error"]
    pairs = [(r["label"], r["judge"]) for r in scored]
    agreement = sum(a == b for a, b in pairs) / len(pairs)
    kappa = cohen_kappa(pairs)
    confusion = Counter(pairs)
    tp, fn = confusion[("ungrounded", "ungrounded")], confusion[("ungrounded", "grounded")]
    fp = confusion[("grounded", "ungrounded")]
    summary = {
        "judge_model": judge.model, "runs_per_row": args.runs, "rows": len(rows), "scored": len(scored),
        "agreement": round(agreement, 3), "cohen_kappa": round(kappa, 3),
        "ungrounded_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "ungrounded_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "confusion": {f"human={a} judge={b}": n for (a, b), n in sorted(confusion.items())},
        "usage": summarize_usage(calls),
    }
    (OUT / "judge_calibration.json").write_text(json.dumps({"summary": summary, "rows": results}, indent=2))
    (OUT / "judge_calibration.md").write_text(render(summary, results))
    print(json.dumps(summary, indent=2))
    return 0


def render(s: dict, rows: list[dict]) -> str:
    lines = [
        "# Judge calibration", "",
        f"The groundedness judge (`{s['judge_model']}`, {s['runs_per_row']} run(s) per row, majority vote) against "
        f"{s['rows']} labelled replies in `judge_labels.jsonl`.", "",
        "| Metric | Value |", "|---|---|",
        f"| Agreement with labels | **{s['agreement']:.0%}** ({s['scored']} scored) |",
        f"| Cohen's kappa | {s['cohen_kappa']:.2f} |",
        f"| Recall on ungrounded replies | {s['ungrounded_recall']:.0%} |" if s["ungrounded_recall"] is not None else None,
        f"| Precision on ungrounded replies | {s['ungrounded_precision']:.0%} |" if s["ungrounded_precision"] is not None else None,
        f"| Judge cost for this run | ${s['usage']['cost_usd']:.4f} ({s['usage']['llm_calls']} calls) |",
        "", "Confusion: " + ", ".join(f"{k}: {v}" for k, v in s["confusion"].items()), "",
        "Labels were written by the author (with AI assistance) against the fact sheet the agent holds; they "
        "should be reviewed by a second person before the agreement number is relied on.", "",
        "## Disagreements", "",
    ]
    bad = [r for r in rows if r["judge"] != r["label"]]
    if not bad:
        lines.append("None.")
    for r in bad:
        lines += [f"- **{r['id']}** (label {r['label']}, judge {r['judge']}, votes {r['votes']}): "
                  f"\"{r['reply']}\" ({r['note']})"]
        lines += [f"    - {f}" for f in r["flagged"][:3]]
    return "\n".join(line for line in lines if line is not None) + "\n"


if __name__ == "__main__":
    sys.exit(main())
