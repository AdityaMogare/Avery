"""Scenario eval runner: pass^k reliability, trace properties and LLM-judged faithfulness.

Usage (from apps/insurance_claims/backend):
    python -m evals.run_evals                 # offline (heuristic + template), k=1
    OPENAI_API_KEY=... python -m evals.run_evals --k 3 --judge
    python -m evals.run_evals --fixtures ../fixtures_alt   # same harness on unseen data -> report_alt.*
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
from app import config  # noqa: E402
from app.fixtures import Repository  # noqa: E402
from app.grounding.factsheet import FactSheet  # noqa: E402
from app.grounding.judge import judge_reply  # noqa: E402
from app.llm import USAGE_SINK, LLMError, summarize_usage  # noqa: E402
from app.pipeline import Agent  # noqa: E402

OUT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=1, help="trials per scenario (pass^k)")
    ap.add_argument("--judge", action="store_true", help="run the LLM groundedness judge on every reply")
    ap.add_argument("--only", nargs="*", help="scenario ids")
    ap.add_argument("--offline", action="store_true", help="ignore OPENAI_API_KEY")
    ap.add_argument("--fixtures", type=Path, help="alternate fixtures dir (with specs/scenarios.json)")
    args = ap.parse_args()

    key = None if args.offline else os.getenv("OPENAI_API_KEY")
    fixtures = args.fixtures.resolve() if args.fixtures else None
    agent = Agent(api_key=key, repo=Repository(fixtures) if fixtures else None)
    scenarios = [s for s in load_scenarios(fixtures) if not args.only or s["id"] in args.only]
    stem = "report" + (f"_{fixtures.name.removeprefix('fixtures_')}" if fixtures else "")
    rows, totals = [], {"claims": 0, "supported": 0, "regenerations": 0, "fallbacks": 0, "turns": 0}
    turn_usage: list[dict] = []        # one entry per agent turn
    convo_usage: list[dict] = []       # one entry per conversation (trial)
    judge_calls: list[dict] = []
    started = time.time()

    for spec in scenarios:
        trials = []
        for _ in range(args.k):
            run = run_scenario(agent, spec)
            usages = [r.usage for r in run.results if r.usage]
            turn_usage.extend(usages)
            convo_usage.append({k: sum(u[k] for u in usages) for k in
                                ("llm_calls", "prompt_tokens", "completion_tokens", "cost_usd", "wall_ms")} if usages else {})
            judged = []
            if args.judge and agent.llm:
                for i, res in enumerate(run.results):
                    facts = FactSheet()
                    for f in res.facts:
                        facts.add(f["id"], f["value"], f["source"])
                    try:
                        convo = "\n".join(f"{m.role.upper()}: {m.content}" for m in run.state.transcript
                                          if m.turn <= i + 1 and not (m.turn == i + 1 and m.role == "assistant"))
                        sink_token = USAGE_SINK.set(judge_calls)
                        try:
                            j = judge_reply(agent.judge_llm, res.reply, facts, spec["turns"][i], convo)
                        finally:
                            USAGE_SINK.reset(sink_token)
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
        "mode": agent.mode, "fixtures": fixtures.name if fixtures else "fixtures", "judge_model": agent.judge_llm.model if agent.judge_llm else None, "k": args.k, "judge": bool(args.judge and agent.llm),
        "scenarios": len(rows), "pass_k": sum(r["pass_k"] for r in rows),
        "faithfulness": (totals["supported"] / totals["claims"]) if totals["claims"] else None,
        **totals, "seconds": round(time.time() - started, 1),
        "usage": usage_summary(turn_usage, convo_usage, judge_calls),
    }
    (OUT / f"{stem}.json").write_text(json.dumps({"summary": summary, "scenarios": rows}, indent=2))
    (OUT / f"{stem}.md").write_text(render_md(summary, rows))
    print(json.dumps(summary, indent=2))
    return 0 if summary["pass_k"] == summary["scenarios"] else 1


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def usage_summary(turns: list[dict], convos: list[dict], judge_calls: list[dict]) -> dict | None:
    if not turns or not any(t["llm_calls"] for t in turns):
        return None
    wall = [t["wall_ms"] for t in turns]
    convos = [c for c in convos if c]
    return {
        "turns": len(turns), "conversations": len(convos),
        "turn_wall_ms_p50": _pct(wall, 0.5), "turn_wall_ms_p95": _pct(wall, 0.95),
        "llm_calls_per_turn": round(sum(t["llm_calls"] for t in turns) / len(turns), 2),
        "tokens_per_turn": round(sum(t["prompt_tokens"] + t["completion_tokens"] for t in turns) / len(turns)),
        "tokens_per_conversation": round(sum(c["prompt_tokens"] + c["completion_tokens"] for c in convos) / len(convos)),
        "cost_usd_per_turn": round(sum(t["cost_usd"] for t in turns) / len(turns), 6),
        "cost_usd_per_conversation": round(sum(c["cost_usd"] for c in convos) / len(convos), 6),
        "cost_usd_per_1k_conversations": round(1000 * sum(c["cost_usd"] for c in convos) / len(convos), 2),
        "judge": summarize_usage(judge_calls) if judge_calls else None,
    }


def render_md(summary: dict, rows: list[dict]) -> str:
    faith = f"{summary['faithfulness']:.3f}" if summary["faithfulness"] is not None else "n/a (judge off)"
    lines = [
        "# Eval report", "",
        f"- Mode: `{summary['mode']}`, fixtures `{summary['fixtures']}`, trials per scenario k={summary['k']}",
        f"- pass^{summary['k']}: **{summary['pass_k']}/{summary['scenarios']}** scenarios",
        f"- Judge faithfulness (supported/total atomic claims): **{faith}** ({summary['supported']}/{summary['claims']})",
        f"- Replies: {summary['turns']} · regenerated after verifier rejection: {summary['regenerations']} · "
        f"template fallbacks: {summary['fallbacks']}",
    ]
    u = summary.get("usage")
    if u:
        lines += [
            "", "## Cost and latency (agent turns, judge excluded)", "",
            "| Metric | Value |", "|---|---|",
            f"| Turn latency p50 / p95 (wall, incl. understand + respond + any regeneration) | {u['turn_wall_ms_p50']:.0f} ms / {u['turn_wall_ms_p95']:.0f} ms |",
            f"| Model calls per turn (mean) | {u['llm_calls_per_turn']} |",
            f"| Tokens per turn / per conversation (mean) | {u['tokens_per_turn']:,} / {u['tokens_per_conversation']:,} |",
            f"| Estimated cost per conversation | ${u['cost_usd_per_conversation']:.4f} (${u['cost_usd_per_1k_conversations']:.2f} per 1,000) |",
        ]
        if u.get("judge"):
            lines.append(f"| Judge (eval only): calls / cost | {u['judge']['llm_calls']} / ${u['judge']['cost_usd']:.4f} |")
        lines.append(f"\nPrices: gpt-5.4-nano list price, USD per 1M tokens: input {config.PRICE_INPUT_PER_M}, "
                     f"cached input {config.PRICE_CACHED_INPUT_PER_M}, output {config.PRICE_OUTPUT_PER_M} "
                     "(override with PRICE_*_PER_M).")
    lines += ["", "| Scenario | pass^k | Notes |", "|---|---|---|"]
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
