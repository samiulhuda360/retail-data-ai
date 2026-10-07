"""Weekly campaign report: gathers the week's marketing numbers through the metrics tools, writes a short
report, and refuses to publish it unless every number in it is grounded in those results.

Writers: the model (when AI_API_KEY is set) or a deterministic template. Both go through the same grounding
check; a model draft that fails is sent back once with the ungrounded numbers, and is rejected if it fails again.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import paths
from ..llm import LLM, NoModel
from ..mcp_client import MetricsTools, metrics_session
from .grounding import ungrounded

PAID = ["paid_search", "paid_social", "display", "email", "affiliate"]
OUT_DIR = paths.BUILD / "reports"


def week_bounds(iso_week: str) -> tuple[date, date]:
    monday = datetime.strptime(iso_week + "-1", "%G-W%V-%u").date()
    return monday, monday + timedelta(days=6)


def _change(this: float | None, prev: float | None) -> float | None:
    if this is None or not prev:
        return None
    return round((this - prev) / prev * 100, 1)


def _pair(this: float | None, prev: float | None, digits: int) -> dict:
    def r(v: float | None) -> float | None:
        return None if v is None else round(v, digits)

    return {"this_week": r(this), "previous_week": r(prev), "change_pct": _change(this, prev)}


async def gather_facts(tools: MetricsTools, iso_week: str) -> dict:
    start, end = week_bounds(iso_week)
    pstart, pend = start - timedelta(days=7), end - timedelta(days=7)

    async def q(
        metrics: list[str], s: date, e: date, group_by: list[str] | None = None, filters: list[dict] | None = None
    ) -> list[dict]:
        req: dict[str, Any] = {"metrics": metrics, "start_date": str(s), "end_date": str(e)}
        if group_by:
            req["group_by"] = group_by
        if filters:
            req["filters"] = filters
        return (await tools.call("query_metric", req))["rows"]

    mkt = ["ad_spend", "attributed_revenue", "roas"]
    paid = [{"dimension": "marketing_channel", "op": "in", "value": PAID}]
    tot_now, tot_prev = (await q(mkt, start, end))[0], (await q(mkt, pstart, pend))[0]
    by_now = {r["marketing_channel"]: r for r in await q(mkt, start, end, ["marketing_channel"], paid)}
    by_prev = {r["marketing_channel"]: r for r in await q(mkt, pstart, pend, ["marketing_channel"], paid)}
    online = [{"dimension": "sales_channel", "op": "=", "value": "online"}]
    web = ["revenue", "orders", "average_order_value"]
    web_now, web_prev = (await q(web, start, end, filters=online))[0], (await q(web, pstart, pend, filters=online))[0]
    regions = await q(["attributed_revenue", "roas"], start, end, ["region"])
    top_region = max((r for r in regions if r["attributed_revenue"]), key=lambda r: r["attributed_revenue"])

    channels = []
    for ch in PAID:
        now, prev = by_now.get(ch, {}), by_prev.get(ch, {})
        channels.append(
            {
                "marketing_channel": ch,
                "ad_spend": _pair(now.get("ad_spend"), prev.get("ad_spend"), 2),
                "attributed_revenue": _pair(now.get("attributed_revenue"), prev.get("attributed_revenue"), 2),
                "roas": _pair(now.get("roas"), prev.get("roas"), 4),
            }
        )
    ranked = sorted((c for c in channels if c["roas"]["this_week"] is not None), key=lambda c: c["roas"]["this_week"])
    return {
        "week": iso_week,
        "period": {"start": str(start), "end": str(end)},
        "previous_period": {"start": str(pstart), "end": str(pend)},
        "totals": {k: _pair(tot_now[k], tot_prev[k], 4 if k == "roas" else 2) for k in mkt},
        "online": {k: _pair(web_now[k], web_prev[k], 2) for k in web},
        "channels": channels,
        "best_channel_by_roas": ranked[-1]["marketing_channel"] if ranked else None,
        "weakest_channel_by_roas": ranked[0]["marketing_channel"] if ranked else None,
        "top_region": {
            "region": top_region["region"],
            "attributed_revenue": round(top_region["attributed_revenue"], 2),
            "roas": round(top_region["roas"], 4) if top_region["roas"] is not None else None,
        },
    }


def _money(v: float) -> str:
    return f"NZD {v:,.0f}"


def _pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{'up' if v >= 0 else 'down'} {abs(v):.1f}%"


def template_report(f: dict) -> str:
    t, o = f["totals"], f["online"]
    best = next(c for c in f["channels"] if c["marketing_channel"] == f["best_channel_by_roas"])
    weak = next(c for c in f["channels"] if c["marketing_channel"] == f["weakest_channel_by_roas"])
    lines = [
        f"# Campaign report, {f['week']} ({f['period']['start']} to {f['period']['end']})",
        "",
        f"**Headline:** paid media returned {t['roas']['this_week']:.2f} in attributed revenue per dollar "
        f"({_pct(t['roas']['change_pct'])} on the week before), from {_money(t['ad_spend']['this_week'])} of spend "
        f"and {_money(t['attributed_revenue']['this_week'])} of attributed online revenue.",
        "",
        "| Channel | Spend | Attributed revenue | ROAS | ROAS vs last week |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in f["channels"]:
        roas = c["roas"]["this_week"]
        lines.append(
            f"| {c['marketing_channel']} | {_money(c['ad_spend']['this_week'] or 0)} | "
            f"{_money(c['attributed_revenue']['this_week'] or 0)} | "
            f"{'n/a' if roas is None else f'{roas:.2f}'} | {_pct(c['roas']['change_pct'])} |"
        )
    lines += [
        "",
        f"- **Online store:** {_money(o['revenue']['this_week'])} revenue ({_pct(o['revenue']['change_pct'])}), "
        f"{o['orders']['this_week']:,.0f} orders, average order value {_money(o['average_order_value']['this_week'])}.",
        f"- **Strongest channel:** {best['marketing_channel']} at ROAS {best['roas']['this_week']:.2f}.",
        f"- **Weakest channel:** {weak['marketing_channel']} at ROAS {weak['roas']['this_week']:.2f}; review its "
        "targeting before adding budget.",
        f"- **Top region:** {f['top_region']['region']} with {_money(f['top_region']['attributed_revenue'])} of "
        "attributed revenue.",
    ]
    return "\n".join(lines) + "\n"


WRITER = """You write the weekly paid-media report for Acme Kitchen Co.'s marketing team.
Use ONLY the numbers in the facts JSON. Do not calculate new numbers (no sums, differences or new percentages);
every number you write must appear in the facts, rounded for display.
Format: money as "NZD 12,345" (no decimals), ROAS with 2 decimals (e.g. 4.21), changes as "up 12.3%" or
"down 4.0%" using change_pct, order counts as whole numbers. Dates as given in the facts.
Structure (Markdown, under 180 words): a "# Campaign report, <week> (<start> to <end>)" title; a one-sentence
**Headline**; 3-5 bullets on channels, the online store and the top region; one bullet "**Action:**" with a
recommendation that follows from the numbers."""


def write_with_model(facts: dict, llm: LLM) -> tuple[str, list[str], int]:
    messages = [
        {"role": "system", "content": WRITER},
        {"role": "user", "content": "Facts:\n" + json.dumps(facts, indent=1)},
    ]
    attempts = 0
    for _ in range(2):
        attempts += 1
        text = llm.chat(messages, temperature=0.2).content.strip()
        text = text.removeprefix("```markdown").removeprefix("```").removesuffix("```").strip() + "\n"
        bad = ungrounded(text, facts)
        if not bad:
            return text, [], attempts
        messages += [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": "These numbers are not in the facts: "
                + ", ".join(bad)
                + ". Rewrite the report using only numbers from the facts.",
            },
        ]
    return text, bad, attempts


async def build(iso_week: str, use_model: bool = True) -> dict:
    async with metrics_session() as tools:
        facts = await gather_facts(tools, iso_week)
        tool_calls = len(tools.calls)
    llm = LLM()
    writer, attempts = "template", 1
    if use_model and llm.available:
        try:
            text, bad, attempts = write_with_model(facts, llm)
            writer = f"model ({llm.model})"
        except NoModel:
            text, bad = template_report(facts), []
    else:
        text = template_report(facts)
        bad = ungrounded(text, facts)
    return {
        "week": iso_week,
        "facts": facts,
        "report": text,
        "ungrounded": bad,
        "writer": writer,
        "attempts": attempts,
        "tool_calls": tool_calls,
    }


def main(iso_week: str, use_model: bool = True, out_dir: Path = OUT_DIR) -> int:
    result = asyncio.run(build(iso_week, use_model))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"campaign_{iso_week}.facts.json").write_text(json.dumps(result["facts"], indent=1) + "\n")
    print(result["report"])
    print(f"writer: {result['writer']}, {result['tool_calls']} metric queries, {result['attempts']} draft(s)")
    if result["ungrounded"]:
        path = out_dir / f"campaign_{iso_week}.rejected.md"
        path.write_text(result["report"], encoding="utf-8")
        print(f"GROUNDING CHECK FAILED: numbers not found in the query results: {', '.join(result['ungrounded'])}")
        print(f"report not published; draft kept at {path}")
        return 1
    path = out_dir / f"campaign_{iso_week}.md"
    path.write_text(result["report"], encoding="utf-8")
    print(f"grounding check passed: every number traced to a query result. Saved {path}")
    return 0
