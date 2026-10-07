"""Builds the data-quality report from dbt's run artifacts and the generator's ground truth.

Inputs: `run_results.json` from `dbt build`, `sources.json` from `dbt source freshness`, `manifest.json` for
test names, the stored failing rows in the `dq_audit` schema, and `ground_truth.json`. Output: a summary
dict plus Markdown and HTML reports that show, for every planted failure, the checks that caught it.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import duckdb
import yaml

EXPECTATIONS = Path(__file__).with_name("expectations.yaml")


@dataclass
class Check:
    name: str
    kind: str  # test | freshness
    status: str  # pass | warn | error | fail
    failures: int
    tags: list[str] = field(default_factory=list)

    @property
    def fired(self) -> bool:
        return self.status in {"warn", "error", "fail", "runtime error"}


@dataclass
class FailureResult:
    id: str
    kind: str
    where: str
    detail: str
    rows: int
    checks: list[Check]
    evidence_rows: int | None
    caught: bool


@dataclass
class DQReport:
    as_of: str
    planted: int
    caught: int
    failures: list[FailureResult]
    detection_checks: list[Check]
    unexplained: list[Check]
    build: dict
    quarantined_lines: int

    def to_dict(self) -> dict:
        return asdict(self)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def collect_checks(target: Path) -> tuple[list[Check], dict]:
    manifest = _load(target / "manifest.json")
    nodes = manifest.get("nodes", {})
    run = _load(target / "run_results.json")
    checks: list[Check] = []
    counts = {"pass": 0, "warn": 0, "error": 0, "fail": 0, "success": 0, "skipped": 0}
    for r in run.get("results", []):
        status = str(r.get("status"))
        counts[status] = counts.get(status, 0) + 1
        uid = r["unique_id"]
        if not uid.startswith("test."):
            continue
        node = nodes.get(uid, {})
        checks.append(
            Check(
                name=node.get("name", uid.split(".")[2]),
                kind="test",
                status=status,
                failures=int(r.get("failures") or 0),
                tags=list(node.get("tags", [])),
            )
        )
    for r in _load(target / "sources.json").get("results", []):
        uid = r["unique_id"]  # source.acme_retail.raw.<table>
        name = "freshness:" + ".".join(uid.split(".")[2:])
        status = str(r.get("status"))
        age_days = round(float(r.get("max_loaded_at_time_ago_in_s") or 0) / 86400, 1)
        checks.append(
            Check(
                name=name,
                kind="freshness",
                status=status,
                failures=int(status != "pass"),
                tags=[f"age {age_days} days"],
            )
        )
    build = {
        "models": sum(1 for r in run.get("results", []) if r["unique_id"].startswith(("model.", "seed."))),
        "tests": sum(1 for c in checks if c.kind == "test"),
        **{k: v for k, v in counts.items() if v},
    }
    return checks, build


def build_report(target: Path, ground_truth: Path, warehouse: Path) -> DQReport:
    checks, build = collect_checks(target)
    by_name = {c.name: c for c in checks}
    expectations = yaml.safe_load(EXPECTATIONS.read_text(encoding="utf-8"))
    truth = _load(ground_truth)
    results: list[FailureResult] = []
    explained: set[str] = set()
    quarantined = 0
    with duckdb.connect(str(warehouse), read_only=True) as con:
        for f in truth.get("failures", []):
            exp = expectations.get(f["kind"], {})
            mapped = [by_name[n] for n in exp.get("checks", []) if n in by_name]
            fired = [c for c in mapped if c.fired]
            evidence = None
            if exp.get("evidence"):
                sql = exp["evidence"].format(**{k: v for k, v in f.items() if isinstance(v, str | int)})
                try:
                    evidence = int(con.execute(sql).fetchone()[0])  # type: ignore[index]
                except duckdb.Error:
                    evidence = 0
            caught = bool(fired) and (evidence is None or evidence > 0)
            explained.update(c.name for c in fired)
            results.append(
                FailureResult(
                    id=f["id"],
                    kind=f["kind"],
                    where=f["where"],
                    detail=f["detail"],
                    rows=int(f.get("rows", 0)),
                    checks=mapped,
                    evidence_rows=evidence,
                    caught=caught,
                )
            )
        try:
            quarantined = int(
                con.execute("select count(*) from intermediate.int_dq__quarantined_pos_lines").fetchone()[0]
            )  # type: ignore[index]
        except duckdb.Error:
            quarantined = 0
    detection = [c for c in checks if "dq_detect" in c.tags or c.kind == "freshness"]
    unexplained = [c for c in checks if c.fired and c.name not in explained]
    return DQReport(
        as_of=truth.get("as_of", ""),
        planted=len(results),
        caught=sum(r.caught for r in results),
        failures=results,
        detection_checks=detection,
        unexplained=unexplained,
        build=build,
        quarantined_lines=quarantined,
    )


def _status(c: Check) -> str:
    return {"pass": "pass", "warn": "WARN", "error": "ERROR", "fail": "FAIL"}.get(c.status, c.status)


def to_markdown(r: DQReport) -> str:
    out = [
        "# Data-quality report",
        "",
        f"Landing zone read as of **{r.as_of} UTC**. Planted failures caught: **{r.caught} of {r.planted}**. "
        f"Checks firing with no planted cause: **{len(r.unexplained)}**. Quarantined till lines: "
        f"**{r.quarantined_lines}**.",
        "",
        "## Planted failures and the checks that caught them",
        "",
        "| ID | Failure | Where | Rows | Caught by | Caught |",
        "|---|---|---|---:|---|---|",
    ]
    for f in r.failures:
        by = "<br>".join(f"`{c.name}` ({_status(c)}, {c.failures})" for c in f.checks if c.fired) or "none"
        out.append(
            f"| {f.id} | {f.kind.replace('_', ' ')} | `{f.where}` | {f.rows} | {by} | {'yes' if f.caught else 'NO'} |"
        )
    out += ["", "## Every detection check", "", "| Check | Type | Status | Failing rows |", "|---|---|---|---:|"]
    for c in sorted(r.detection_checks, key=lambda c: (not c.fired, c.name)):
        extra = f" ({c.tags[0]})" if c.kind == "freshness" and c.tags else ""
        out.append(f"| `{c.name}`{extra} | {c.kind} | {_status(c)} | {c.failures} |")
    if r.unexplained:
        out += ["", "## Checks that fired without a planted cause", ""]
        out += [f"- `{c.name}`: {_status(c)} ({c.failures})" for c in r.unexplained]
    b = r.build
    out += [
        "",
        f"dbt build: {b.get('models', 0)} models and seeds, {b.get('tests', 0)} tests "
        f"({', '.join(f'{k} {v}' for k, v in b.items() if k not in {'models', 'tests'})}).",
        "",
    ]
    return "\n".join(out)


def to_html(r: DQReport) -> str:
    def esc(s: object) -> str:
        return html.escape(str(s))

    rows = []
    for f in r.failures:
        chips = (
            "".join(
                f'<span class="chip {c.status}">{esc(c.name)} <b>{esc(_status(c))}</b> {c.failures}</span>'
                for c in f.checks
                if c.fired
            )
            or '<span class="muted">none</span>'
        )
        rows.append(
            f"<tr><td class='id'>{esc(f.id)}</td><td><b>{esc(f.kind.replace('_', ' '))}</b>"
            f"<div class='muted'>{esc(f.detail)}</div></td><td><code>{esc(f.where)}</code></td>"
            f"<td class='num'>{f.rows}</td><td>{chips}</td>"
            f"<td class='{'ok' if f.caught else 'bad'}'>{'caught' if f.caught else 'MISSED'}</td></tr>"
        )
    checks = []
    for c in sorted(r.detection_checks, key=lambda c: (not c.fired, c.name)):
        extra = f" <span class='muted'>({esc(c.tags[0])})</span>" if c.kind == "freshness" and c.tags else ""
        checks.append(
            f"<tr><td><code>{esc(c.name)}</code>{extra}</td><td>{esc(c.kind)}</td>"
            f"<td><span class='chip {c.status}'>{esc(_status(c))}</span></td>"
            f"<td class='num'>{c.failures}</td></tr>"
        )
    b = r.build
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Data-quality report</title>
<style>
:root {{ --bg:#f5f7f6; --card:#ffffff; --ink:#13302c; --muted:#5f7471; --line:#d9e3e0; --teal:#2f6f68;
        --tealbg:#e6f2ef; --warn:#a86a12; --warnbg:#fbf0dc; --err:#a3352b; --errbg:#f8e3e0; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 "Segoe UI", system-ui, sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:28px 20px 40px; }}
h1 {{ margin:0 0 4px; font-size:26px; }} h2 {{ font-size:18px; margin:28px 0 10px; }}
.sub {{ color:var(--muted); margin-bottom:18px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }}
.kpi b {{ display:block; font-size:26px; color:var(--teal); }} .kpi span {{ color:var(--muted); font-size:13px; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px;
        overflow:hidden; }}
th, td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
th {{ background:var(--tealbg); font-size:13px; }} td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.id {{ font-weight:600; color:var(--teal); }} code {{ font-size:12.5px; }}
.muted {{ color:var(--muted); font-size:13px; }}
.chip {{ display:inline-block; margin:2px 4px 2px 0; padding:1px 8px; border-radius:999px; font-size:12px;
        background:var(--tealbg); color:var(--teal); }}
.chip.warn {{ background:var(--warnbg); color:var(--warn); }} .chip.error, .chip.fail {{ background:var(--errbg); color:var(--err); }}
td.ok {{ color:var(--teal); font-weight:600; }} td.bad {{ color:var(--err); font-weight:700; }}
</style></head><body><main>
<h1>Data-quality report</h1>
<div class="sub">Acme Kitchen Co. landing zone, read as of {esc(r.as_of)} UTC</div>
<div class="kpis">
<div class="kpi"><b>{r.caught} / {r.planted}</b><span>planted failures caught</span></div>
<div class="kpi"><b>{len(r.unexplained)}</b><span>checks firing without a planted cause</span></div>
<div class="kpi"><b>{r.quarantined_lines}</b><span>till lines quarantined</span></div>
<div class="kpi"><b>{b.get("tests", 0)}</b><span>dbt tests ({b.get("pass", 0)} pass, {b.get("warn", 0)} warn, {b.get("error", 0)} error)</span></div>
</div>
<h2>Planted failures and the checks that caught them</h2>
<table><tr><th>ID</th><th>Failure</th><th>Where</th><th>Rows</th><th>Caught by (status, failing rows)</th><th></th></tr>
{"".join(rows)}</table>
<h2>Detection checks</h2>
<table><tr><th>Check</th><th>Type</th><th>Status</th><th>Failing rows</th></tr>{"".join(checks)}</table>
</main></body></html>
"""


def write_reports(r: DQReport, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown": out_dir / "dq_report.md",
        "html": out_dir / "dq_report.html",
        "json": out_dir / "dq_report.json",
    }
    paths["markdown"].write_text(to_markdown(r), encoding="utf-8")
    paths["html"].write_text(to_html(r), encoding="utf-8")
    paths["json"].write_text(json.dumps(r.to_dict(), indent=2) + "\n", encoding="utf-8")
    return paths
