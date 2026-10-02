"""Scenario eval runner: pass^k reliability, trace properties and LLM-judged faithfulness.

Usage (from apps/insurance_claims/backend):
    python -m evals.run_evals                 # offline (heuristic + template), k=1
    OPENAI_API_KEY=... python -m evals.run_evals --k 3 --judge
Writes evals/report.md and evals/report.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("OUTBOX_DIR", tempfile.mkdtemp(prefix="sop-eval-outbox-"))

from app.evaluation import load_scenarios, run_scenario  # noqa: E402
from app.grounding.factsheet import FactSheet  # noqa: E402
from app.grounding.judge import judge_reply  # noqa: E402
from app.llm import LLMError  # noqa: E402
from app.pipeline import Agent  # noqa: E402

OUT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=1, help="trials per scenario (pass^k)")
    ap.add_argument("--judge", action="store_true", help="run the LLM groundedness judge on every reply")
    ap.add_argument("--only", nargs="*", help="scenario ids")
    ap.add_argument("--offline", action="store_true", help="ignore OPENAI_API_KEY")
    args = ap.parse_args()

    key = None if args.offline else os.getenv("OPENAI_API_KEY")
    agent = Agent(api_key=key)
    scenarios = [s for s in load_scenarios() if not args.only or s["id"] in args.only]
    rows, totals = [], {"claims": 0, "supported": 0, "regenerations": 0, "fallbacks": 0, "turns": 0}
    started = time.time()

    for spec in scenarios:
        trials = []
        for _ in range(args.k):
            run = run_scenario(agent, spec)
            judged = []
            if args.judge and agent.llm:
                for i, res in enumerate(run.results):
                    facts = FactSheet()
                    for f in res.facts:
                        facts.add(f["id"], f["value"], f["source"])
                    try:
                        convo = "\n".join(f"{m.role.upper()}: {m.content}" for m in run.state.transcript
                                          if m.turn <= i + 1 and not (m.turn == i + 1 and m.role == "assistant"))
                        j = judge_reply(agent.judge_llm, res.reply, facts, spec["turns"][i], convo)
                        judged.extend(j.factual)
                        for c in j.factual:
                            if c.verdict != "supported":
                                run.failures.append(f"judge turn {i + 1}: {c.verdict}: {c.claim} ({c.reason})")
                    except LLMError as exc:
                        run.failures.append(f"judge error: {exc}")
            totals["claims"] += len(judged)
            totals["supported"] += sum(c.verdict == "supported" for c in judged)
            for e in run.state.trace:
                if e.type == "response":
                    totals["turns"] += 1
                    totals["regenerations"] += e.data["responder"] == "llm_regenerated"
                    totals["fallbacks"] += e.data["responder"] == "template_fallback"
            trials.append(run)
        passed = sum(t.passed for t in trials)
        rows.append({
            "id": spec["id"], "description": spec["description"], "trials": args.k, "passed": passed,
            "pass_k": passed == args.k,
            "failures": sorted({f for t in trials for f in t.failures}),
            "trace_properties": trials[-1].trace_properties,
            "transcript": [{"role": m.role, "content": m.content} for m in trials[-1].state.transcript],
        })
        print(f"{'PASS' if passed == args.k else 'FAIL'}  {spec['id']}  ({passed}/{args.k})", flush=True)

    summary = {
        "mode": agent.mode, "judge_model": agent.judge_llm.model if agent.judge_llm else None, "k": args.k, "judge": bool(args.judge and agent.llm),
        "scenarios": len(rows), "pass_k": sum(r["pass_k"] for r in rows),
        "faithfulness": (totals["supported"] / totals["claims"]) if totals["claims"] else None,
        **totals, "seconds": round(time.time() - started, 1),
    }
    (OUT / "report.json").write_text(json.dumps({"summary": summary, "scenarios": rows}, indent=2))
    (OUT / "report.md").write_text(render_md(summary, rows))
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass_k"] == summary["scenarios"] else 1


def render_md(summary: dict, rows: list[dict]) -> str:
    faith = f"{summary['faithfulness']:.3f}" if summary["faithfulness"] is not None else "n/a (judge off)"
    lines = [
        "# Eval report", "",
        f"- Mode: `{summary['mode']}`, trials per scenario k={summary['k']}",
        f"- pass^{summary['k']}: **{summary['pass_k']}/{summary['scenarios']}** scenarios",
        f"- Judge faithfulness (supported/total atomic claims): **{faith}** ({summary['supported']}/{summary['claims']})",
        f"- Replies: {summary['turns']} · regenerated after verifier rejection: {summary['regenerations']} · "
        f"template fallbacks: {summary['fallbacks']}",
        "", "| Scenario | pass^k | Notes |", "|---|---|---|",
    ]
    for r in rows:
        notes = "<br>".join(r["failures"][:4]).replace("|", "\\|") or "all expectations + trace properties hold"
        lines.append(f"| `{r['id']}` | {'✅' if r['pass_k'] else '❌'} {r['passed']}/{r['trials']} | {notes} |")
    lines += ["", "## Transcripts (last trial)", ""]
    for r in rows:
        lines.append(f"### {r['id']}\n_{r['description']}_\n")
        lines += [f"- **{m['role']}**: {m['content']}" for m in r["transcript"]]
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
