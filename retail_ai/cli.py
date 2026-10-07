"""Command line for the retail data platform.

retail generate [--clean]     write the landing zone (data/raw) and its ground truth
retail ingest                 load the landing zone into the warehouse's raw schema
retail build                  dbt source freshness + dbt build (models, seeds, tests)
retail dq [--alert URL]       data-quality report (build/dq) and the webhook alert
retail legacy                 run the legacy pandas reports (build/legacy)
retail compare                compare the legacy reports with the dbt marts
retail pipeline [--clean]     all of the above in order
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import paths


def cmd_generate(a: argparse.Namespace) -> int:
    from .generator import generate

    summary = generate(paths.RAW, paths.GROUND_TRUTH, clean=a.clean, seed=a.seed, late_dir=paths.LATE)
    kind = "clean" if a.clean else f"{summary['failures']} planted failures"
    print(f"wrote {summary['files']} files to {paths.RAW} ({kind}); ground truth in {paths.GROUND_TRUTH}")
    return 0


def cmd_ingest(_: argparse.Namespace) -> int:
    from .ingest import ingest

    for t in ingest(paths.RAW, paths.WAREHOUSE):
        print(f"raw.{t.table:<22} {t.files:>3} files {t.rows:>8} rows")
    return 0


def cmd_build(_: argparse.Namespace) -> int:
    from .pipeline import build

    results = build()
    return 0 if results["build"].success else 1


def cmd_dq(a: argparse.Namespace) -> int:
    from .dq import alert
    from .dq.report import build_report, to_markdown, write_reports

    report = build_report(paths.DBT_TARGET, paths.GROUND_TRUTH, paths.WAREHOUSE)
    written = write_reports(report, paths.BUILD / "dq")
    print(to_markdown(report))
    print(f"reports: {written['markdown']}, {written['html']}")
    sent = alert.send(report, a.alert)
    if sent:
        print(f"alert sent: {sent['severity']}, {sent['summary']}")
    missed = report.planted - report.caught
    return 1 if missed or (report.planted == 0 and report.unexplained) else 0


def cmd_legacy(_: argparse.Namespace) -> int:
    script = Path(__file__).parent / "legacy" / "legacy_reports.py"
    return subprocess.call([sys.executable, str(script), str(paths.RAW), str(paths.BUILD / "legacy")])


def cmd_compare(_: argparse.Namespace) -> int:
    from .compare import compare, to_markdown

    diffs = compare(paths.BUILD / "legacy", paths.WAREHOUSE)
    print(to_markdown(diffs))
    for d in diffs:
        for ex in d.examples[:3]:
            print(f"  {d.report}: {json.dumps(ex, default=str)}")
    return 0


def cmd_pipeline(a: argparse.Namespace) -> int:
    steps = [cmd_generate, cmd_ingest, cmd_build, cmd_dq, cmd_legacy, cmd_compare]
    codes = []
    for step in steps:
        print(f"\n== {step.__name__.removeprefix('cmd_')} ==")
        codes.append(step(a))
    return 0 if codes[2] == 0 and codes[3] == 0 else 1


def cmd_ask(a: argparse.Namespace) -> int:
    import asyncio

    from .agent import analyst
    from .llm import LLM, NoModel
    from .mcp_client import metrics_session

    async def go() -> int:
        llm = LLM()
        async with metrics_session() as tools:
            try:
                run = await analyst.answer(a.question, tools, llm)
            except NoModel as e:
                print(f"{e}. Set AI_API_KEY to ask questions; the metrics tools work without it (see mcp-server).")
                return 2
        print(f"Q: {a.question}")
        for call in run.tool_calls:
            print(f"  -> {call['tool']}({json.dumps(call['arguments'])})")
        rows = (run.last_result or {}).get("rows") or []
        if rows:
            cols = list(rows[0])
            fmt = [lambda v: f"{v:,.4f}" if isinstance(v, float) else str(v)][0]
            widths = [max(len(c), *(len(fmt(r[c])) for r in rows[:12])) for c in cols]
            print("     " + "  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)))
            for r in rows[:12]:
                print("     " + "  ".join(fmt(r[c]).ljust(w) for c, w in zip(cols, widths, strict=True)))
        print(f"A: {run.explanation or run.answer}")
        print(
            f"({run.llm_calls} model calls, {run.prompt_tokens + run.completion_tokens} tokens, {run.latency_s:.2f}s)"
        )
        return 0 if not run.error else 1

    return asyncio.run(go())


def cmd_report(a: argparse.Namespace) -> int:
    from .agent.campaign_report import main as report_main

    return report_main(a.week, use_model=not a.no_model)


def cmd_eval(a: argparse.Namespace) -> int:
    from .eval.run import SYSTEMS
    from .eval.run import main as eval_main

    if a.report:
        from .eval.run import combined_report

        print(combined_report())
        return 0
    systems = a.systems.split(",") if a.systems else list(SYSTEMS)
    ids = a.ids.split(",") if a.ids else None
    return eval_main(systems, a.split, offline=a.offline, oracle=a.oracle, ids=ids)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="retail", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="write the landing zone and ground truth")
    g.add_argument("--clean", action="store_true", help="no planted failures")
    g.add_argument("--seed", type=int, default=42)
    g.set_defaults(func=cmd_generate)
    sub.add_parser("ingest", help="load raw files into DuckDB").set_defaults(func=cmd_ingest)
    sub.add_parser("build", help="dbt source freshness and dbt build").set_defaults(func=cmd_build)
    d = sub.add_parser("dq", help="data-quality report and alert")
    d.add_argument("--alert", help="webhook URL (default: $DQ_WEBHOOK_URL)")
    d.set_defaults(func=cmd_dq)
    sub.add_parser("legacy", help="run the legacy pandas reports").set_defaults(func=cmd_legacy)
    sub.add_parser("compare", help="legacy reports vs dbt marts").set_defaults(func=cmd_compare)
    p = sub.add_parser("pipeline", help="generate, ingest, build, dq, legacy, compare")
    p.add_argument("--clean", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--alert", help="webhook URL (default: $DQ_WEBHOOK_URL)")
    p.set_defaults(func=cmd_pipeline)
    q = sub.add_parser("ask", help="ask the analyst agent a question")
    q.add_argument("question")
    q.set_defaults(func=cmd_ask)
    r = sub.add_parser("campaign-report", help="weekly campaign report with a grounding check")
    r.add_argument("--week", default="2026-W13", help="ISO week, e.g. 2026-W13")
    r.add_argument("--no-model", action="store_true", help="use the template writer even if a key is set")
    r.set_defaults(func=cmd_report)
    e = sub.add_parser("eval", help="evaluation: text-to-SQL baseline vs semantic agent")
    e.add_argument("--split", choices=["dev", "holdout", "all"], default="all")
    e.add_argument("--systems", help="comma-separated: baseline,semantic_agent")
    e.add_argument("--ids", help="comma-separated question ids (debug runs are not saved)")
    e.add_argument("--offline", action="store_true", help="use cached model responses only")
    e.add_argument("--oracle", action="store_true", help="no model: check the semantic layer against references")
    e.add_argument("--report", action="store_true", help="rebuild eval/results/summary.md from the recorded runs")
    e.set_defaults(func=cmd_eval)
    a = ap.parse_args(argv)
    return int(a.func(a))


if __name__ == "__main__":
    sys.exit(main())
