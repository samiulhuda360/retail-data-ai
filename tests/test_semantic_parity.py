"""The MCP server's metric compiler must give the same numbers as MetricFlow for every headline metric and dimension.

Both read the same definitions (dbt's semantic manifest). MetricFlow (`mf query`) is the reference engine; the
TypeScript compiler is what the MCP server runs, because it answers in milliseconds instead of seconds.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from retail_ai import paths

pytestmark = [pytest.mark.pipeline, pytest.mark.slow]

HEADLINE = ["revenue", "gross_margin", "average_order_value", "roas", "on_time_delivery_rate"]
# friendly dimension -> (MetricFlow group-by name, metrics that support it)
CASES = {
    "date": ("metric_time__month", HEADLINE),
    "region": ("region__region_name", HEADLINE),
    "country": ("region__country", HEADLINE),
    "sales_channel": (
        "sales_channel__channel_name",
        ["revenue", "gross_margin", "average_order_value", "on_time_delivery_rate"],
    ),
    "product_category": ("product__product_category", ["revenue", "gross_margin"]),
    "marketing_channel": ("marketing_channel__channel_name", ["average_order_value", "roas"]),
    "carrier": ("shipment__carrier", ["on_time_delivery_rate"]),
}
CLI = paths.MCP_DIR / "dist" / "src" / "cli.js"


def _mf(metrics: list[str], group_by: str, out: Path) -> dict[str, dict[str, float | None]]:
    mf = Path(sys.executable).with_name("mf.exe" if os.name == "nt" else "mf")
    env = {**os.environ, "RETAIL_WAREHOUSE": str(paths.WAREHOUSE), "PYTHONIOENCODING": "utf-8"}
    subprocess.run(
        [str(mf), "query", "--metrics", ",".join(metrics), "--group-by", group_by, "--csv", str(out)],
        cwd=paths.DBT_DIR,
        env=env,
        check=True,
        capture_output=True,
        timeout=300,
    )
    with out.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    result = {}
    for r in rows:
        key = r[group_by][:10] if group_by.startswith("metric_time") else r[group_by]  # time comes as a timestamp
        result[key] = {m: float(r[m]) if r[m] not in ("", None) else None for m in metrics}
    return result


def _ts(metrics: list[str], dim: str) -> dict[str, dict[str, float | None]]:
    req = {"metrics": metrics, "group_by": [dim], "grain": "month"}
    proc = subprocess.run(
        ["node", str(CLI), "query", json.dumps(req)],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "RETAIL_WAREHOUSE": str(paths.WAREHOUSE)},
        timeout=120,
    )
    rows = json.loads(proc.stdout)["rows"]
    return {str(r[dim]) if r[dim] is not None else "": {m: r[m] for m in metrics} for r in rows}


@pytest.mark.skipif(shutil.which("node") is None or not CLI.exists(), reason="build the MCP server first")
@pytest.mark.parametrize("dim", list(CASES))
def test_compiler_matches_metricflow(dim, built_warehouse, tmp_path):
    group_by, metrics = CASES[dim]
    expected = _mf(metrics, group_by, tmp_path / "mf.csv")
    actual = _ts(metrics, dim)
    assert set(actual) == set(expected), (sorted(actual), sorted(expected))
    for key, values in expected.items():
        for m, want in values.items():
            got = actual[key][m]
            if want is None:
                assert got in (None, 0), (dim, key, m, got)
            else:
                assert got is not None and abs(got - want) <= 1e-6 * max(1.0, abs(want)), (dim, key, m, got, want)
