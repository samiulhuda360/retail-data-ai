"""An HTML view of the recorded evaluation (eval/results/summary.html)."""

from __future__ import annotations

import html


def _esc(v: object) -> str:
    return html.escape(str(v))


def _val(v: object) -> str:
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return _esc(v)
    if isinstance(v, int) and not isinstance(v, bool):
        v = float(v)
    if isinstance(v, float):
        return f"{v:,.4f}" if abs(v) < 100 else f"{v:,.2f}"
    return _esc(v)


def render(summary: list[dict], rows: list[dict], model: str, live: int, cached: int) -> str:
    total = {s["system"]: s for s in summary if s["split"] == "all"}
    base, agent = total.get("baseline", {}), total.get("semantic_agent", {})
    table = "".join(
        f"<tr><td><b>{_esc(s['system'].replace('_', ' '))}</b></td><td>{_esc(s['split'])}</td>"
        f"<td class=n>{s['correct']}/{s['questions']}</td><td class=n><b>{s['accuracy']:.0%}</b></td>"
        f"<td class=n>{s['latency_mean_s']:.2f} s</td><td class=n>{s['latency_p90_s']:.2f} s</td>"
        f"<td class=n>{s['tokens_per_question']:,}</td><td class=n>{s['llm_calls']} ({s['cached_calls']})</td>"
        f"<td class=n>{s['cost_usd']:.4f}</td></tr>"
        for s in summary
    )
    ids = sorted({r["id"] for r in rows})
    by = {(r["id"], r["system"]): r for r in rows if "skipped" not in r}
    grid = []
    for qid in ids:
        b, a = by.get((qid, "baseline")), by.get((qid, "semantic_agent"))
        ref = (a or b or {}).get("expected")
        split = (a or b or {}).get("split", "")
        question = (a or b or {}).get("question", "")

        def cell(r: dict | None) -> str:
            if r is None:
                return "<td>-</td>"
            mark = "ok" if r["correct"] else "miss"
            return f"<td class='{mark}'>{_val(r['answer'])}</td>"

        grid.append(
            f"<tr><td class=id>{qid}</td><td class=split>{_esc(split)}</td><td>{_esc(question)}</td>"
            f"<td class=n>{_val(ref)}</td>{cell(b)}{cell(a)}</tr>"
        )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Evaluation results</title>
<style>
:root {{ --bg:#f5f7f6; --card:#fff; --ink:#13302c; --muted:#5f7471; --line:#d9e3e0; --teal:#2f6f68; --tealbg:#e6f2ef;
        --err:#a3352b; --errbg:#f8e3e0; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14.5px/1.45 "Segoe UI", system-ui, sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:26px 20px 36px; }}
h1 {{ margin:0 0 4px; font-size:25px; }} h2 {{ font-size:17px; margin:24px 0 10px; }}
.sub {{ color:var(--muted); margin-bottom:16px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:13px 16px; }}
.kpi b {{ display:block; font-size:25px; color:var(--teal); }} .kpi span {{ color:var(--muted); font-size:13px; }}
.kpi b.low {{ color:var(--err); }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); }}
th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ background:var(--tealbg); font-size:12.5px; }} td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.id {{ font-weight:600; color:var(--teal); }} td.split {{ color:var(--muted); font-size:12.5px; }}
td.ok {{ background:var(--tealbg); color:var(--teal); text-align:right; font-variant-numeric:tabular-nums; }}
td.miss {{ background:var(--errbg); color:var(--err); text-align:right; font-variant-numeric:tabular-nums; }}
</style></head><body><main>
<h1>Evaluation: text-to-SQL vs the semantic-layer agent</h1>
<div class="sub">40 business questions (30 dev, 10 holdout), answers scored against independent reference values.
Model {_esc(model)}; {live} live model calls, {cached} from cache.</div>
<div class="kpis">
<div class="kpi"><b>{agent.get("correct", 0)}/{agent.get("questions", 0)}</b><span>semantic agent correct</span></div>
<div class="kpi"><b class="low">{base.get("correct", 0)}/{base.get("questions", 0)}</b><span>text-to-SQL baseline correct</span></div>
<div class="kpi"><b>{agent.get("latency_mean_s", 0):.2f} s</b><span>agent mean latency (baseline {base.get("latency_mean_s", 0):.2f} s)</span></div>
<div class="kpi"><b>{agent.get("tokens_per_question", 0):,}</b><span>agent tokens per question (baseline {base.get("tokens_per_question", 0):,})</span></div>
</div>
<h2>Summary</h2>
<table><tr><th>System</th><th>Split</th><th>Correct</th><th>Accuracy</th><th>Mean latency</th><th>p90 latency</th>
<th>Tokens / question</th><th>Model calls (cached)</th><th>Cost USD</th></tr>{table}</table>
<h2>Every question</h2>
<table><tr><th>ID</th><th>Split</th><th>Question</th><th>Reference</th><th>Baseline</th><th>Semantic agent</th></tr>
{"".join(grid)}</table>
</main></body></html>
"""
