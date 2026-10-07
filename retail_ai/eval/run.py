"""Evaluation: 40 business questions, two systems, scored against independent reference answers.

    baseline        plain text-to-SQL over the staging layer (and reference seeds)
    semantic_agent  the analyst agent through the MCP server's semantic-layer tools

Measured per question: correct or not, latency (model time of the live call plus tool or SQL time; waiting
between calls for the rate limit is excluded), tokens and estimated cost. Model responses are cached in
eval/cache, so `--offline` re-scores the recorded run without calling the model.

`--oracle` needs no model: it runs each question's exact semantic-layer query and checks it against the
reference, which validates the question set and the warehouse (this is what CI runs).
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
from datetime import UTC, datetime
from typing import Any

from .. import paths
from ..agent import analyst, text_to_sql
from ..llm import LLM, NoModel, cost_usd
from ..mcp_client import metrics_session
from .reference import Question, load_questions, reference_answers
from .scoring import is_correct, oracle_answer, oracle_request

RESULTS = paths.EVAL_DIR / "results"
LLM_CACHE = paths.EVAL_DIR / "cache"
SYSTEMS = ("baseline", "semantic_agent")


def _fmt(v: Any) -> Any:
    return round(v, 6) if isinstance(v, float) else v


async def run_oracle(questions: list[Question], refs: dict[str, dict]) -> list[dict]:
    rows = []
    async with metrics_session() as tools:
        for q in questions:
            result = await tools.call("query_metric", oracle_request(q))
            got = oracle_answer(q, result)
            rows.append(
                {
                    "id": q.id,
                    "split": q.split,
                    "expected": _fmt(refs[q.id]["answer"]),
                    "answer": _fmt(got),
                    "correct": is_correct(q, refs[q.id]["answer"], got),
                }
            )
    return rows


async def run_models(
    questions: list[Question], refs: dict[str, dict], systems: list[str], llm: LLM, progress: bool = True
) -> list[dict]:
    rows: list[dict] = []
    ctx = text_to_sql.build_context(paths.WAREHOUSE, paths.DBT_TARGET) if "baseline" in systems else None
    async with metrics_session() as tools:
        catalogue = (await tools.call("list_metrics"))["metrics"]
        for q in questions:
            for system in systems:
                try:
                    if system == "baseline":
                        assert ctx is not None
                        run = text_to_sql.answer(q.question, llm, ctx)
                    else:
                        run = await analyst.answer(q.question, tools, llm, catalogue)
                except NoModel as e:
                    rows.append({"id": q.id, "split": q.split, "system": system, "skipped": str(e)})
                    continue
                expected = refs[q.id]["answer"]
                row = {
                    "id": q.id,
                    "split": q.split,
                    "system": system,
                    "question": q.question,
                    "kind": q.kind,
                    "expected": _fmt(expected),
                    "answer": _fmt(run.answer) if not isinstance(run.answer, str) else run.answer,
                    "correct": is_correct(q, expected, run.answer),
                    "error": run.error,
                    "latency_s": run.latency_s,
                    "llm_calls": run.llm_calls,
                    "cached_calls": run.cached_calls,
                    "prompt_tokens": run.prompt_tokens,
                    "completion_tokens": run.completion_tokens,
                    "cost_usd": round(cost_usd(run.prompt_tokens, run.completion_tokens), 6),
                    "tool_calls": run.tool_calls,
                }
                if row["answer"] is not None and not isinstance(row["answer"], str | int | float | bool):
                    row["answer"] = str(row["answer"])
                rows.append(row)
                if progress:
                    mark = "ok " if row["correct"] else "MISS"
                    print(
                        f"{q.id} {system:<15} {mark} expected={row['expected']!s:<22} got={row['answer']!s:<22} "
                        f"{row['latency_s']:.2f}s {row['prompt_tokens'] + row['completion_tokens']} tok"
                        f"{' (cached)' if row['cached_calls'] == row['llm_calls'] else ''}"
                        f"{'  ' + row['error'] if row['error'] else ''}",
                        flush=True,
                    )
    return rows


def summarise(rows: list[dict]) -> list[dict]:
    out = []
    for system in SYSTEMS:
        for split in ("dev", "holdout", "all"):
            sel = [
                r
                for r in rows
                if r.get("system") == system and "skipped" not in r and (split == "all" or r["split"] == split)
            ]
            if not sel:
                continue
            lat = [r["latency_s"] for r in sel]
            out.append(
                {
                    "system": system,
                    "split": split,
                    "questions": len(sel),
                    "correct": sum(r["correct"] for r in sel),
                    "accuracy": round(sum(r["correct"] for r in sel) / len(sel), 3),
                    "latency_mean_s": round(statistics.mean(lat), 2),
                    "latency_median_s": round(statistics.median(lat), 2),
                    "latency_p90_s": round(sorted(lat)[max(0, math.ceil(0.9 * len(lat)) - 1)], 2),
                    "tokens_per_question": round(
                        statistics.mean(r["prompt_tokens"] + r["completion_tokens"] for r in sel)
                    ),
                    "llm_calls": sum(r["llm_calls"] for r in sel),
                    "cached_calls": sum(r["cached_calls"] for r in sel),
                    "cost_usd": round(sum(r["cost_usd"] for r in sel), 4),
                    "errors": sum(bool(r["error"]) for r in sel),
                }
            )
    return out


def to_markdown(summary: list[dict], rows: list[dict], model: str) -> str:
    lines = [
        f"Model: `{model}`. Cost is estimated from tokens at the list prices in `retail_ai/llm.py`.",
        "",
        "| System | Split | Correct | Accuracy | Mean latency | p90 latency | Tokens / question | Model calls "
        "(cached) | Cost (USD) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summary:
        lines.append(
            f"| {s['system']} | {s['split']} | {s['correct']}/{s['questions']} | {s['accuracy']:.0%} | "
            f"{s['latency_mean_s']:.2f} s | {s['latency_p90_s']:.2f} s | {s['tokens_per_question']:,} | "
            f"{s['llm_calls']} ({s['cached_calls']}) | {s['cost_usd']:.4f} |"
        )
    misses = [r for r in rows if "skipped" not in r and not r["correct"]]
    if misses:
        lines += [
            "",
            "Questions answered incorrectly:",
            "",
            "| ID | Split | System | Expected | Answer | Note |",
            "|---|---|---|---|---|---|",
        ]
        for r in misses:
            exp = f"{r['expected']:.4f}" if isinstance(r["expected"], float) else r["expected"]
            ans = f"{r['answer']:.4f}" if isinstance(r["answer"], float) else r["answer"]
            lines.append(f"| {r['id']} | {r['split']} | {r['system']} | {exp} | {ans} | {r['error'] or ''} |")
    return "\n".join(lines) + "\n"


def main(systems: list[str], split: str, offline: bool, oracle: bool, ids: list[str] | None = None) -> int:
    questions = [q for q in load_questions() if (split == "all" or q.split == split) and (not ids or q.id in ids)]
    refs = reference_answers(questions)
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if oracle:
        rows = asyncio.run(run_oracle(questions, refs))
        correct = sum(r["correct"] for r in rows)
        (RESULTS / "oracle.json").write_text(json.dumps({"run_at": stamp, "rows": rows}, indent=1) + "\n")
        for r in rows:
            print(f"{r['id']} {'ok ' if r['correct'] else 'MISS'} expected={r['expected']} oracle={r['answer']}")
        print(f"oracle: {correct}/{len(rows)} semantic-layer answers match the independent references")
        return 0 if correct == len(rows) else 1
    llm = LLM(cache_dir=LLM_CACHE, offline=offline)
    if not llm.available:
        print("No AI_API_KEY set: run with --offline to re-score the recorded run, or --oracle for the no-model check.")
        return 2
    rows = asyncio.run(run_models(questions, refs, systems, llm))
    summary = summarise(rows)
    md = to_markdown(summary, rows, llm.model)
    if not ids:  # partial runs are for debugging and do not replace the recorded results
        body = {
            "run_at": stamp,
            "model": llm.model,
            "live_calls": llm.live_calls,
            "cached_calls": llm.cached_calls,
            "summary": summary,
            "rows": rows,
        }
        (RESULTS / f"results_{split}.json").write_text(json.dumps(body, indent=1, default=str) + "\n")
        (RESULTS / f"summary_{split}.md").write_text(md)
    print()
    print(md)
    print(f"model calls this run: {llm.live_calls} live, {llm.cached_calls} from cache")
    return 0
