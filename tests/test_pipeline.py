"""End-to-end checks on the built warehouse (planted failures), and a full clean run in a temporary folder."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import duckdb
import pytest

from retail_ai import paths
from retail_ai.dq import alert
from retail_ai.dq.mock_webhook import serve_in_background
from retail_ai.dq.report import build_report

pytestmark = pytest.mark.pipeline


def test_every_planted_failure_is_caught_with_evidence(built_warehouse):
    report = build_report(paths.DBT_TARGET, paths.GROUND_TRUTH, built_warehouse)
    assert report.planted == 6
    assert report.caught == 6, [f.id for f in report.failures if not f.caught]
    assert report.unexplained == []
    for f in report.failures:
        assert f.evidence_rows is None or f.evidence_rows > 0, f.id


def test_marts_reconcile_with_finance_after_cleaning(built_warehouse):
    with duckdb.connect(str(built_warehouse), read_only=True) as con:
        off = con.execute("""select count(*) from reporting.rpt_pos_finance_reconciliation
                             where abs(difference_nzd) > 0.05 and quarantined_lines = 0""").fetchone()[0]
        quarantined = con.execute("select count(*) from intermediate.int_dq__quarantined_pos_lines").fetchone()[0]
        dupes = con.execute(
            """select count(*) - count(distinct sales_line_id) from marts.fct_sales_lines"""
        ).fetchone()[0]
        unknown = con.execute("select count(*) from marts.dim_products where is_inferred").fetchone()[0]
    assert off == 0 and quarantined == 1 and dupes == 0 and unknown == 1


def test_alert_reaches_the_webhook(built_warehouse, tmp_path):
    report = build_report(paths.DBT_TARGET, paths.GROUND_TRUTH, built_warehouse)
    out = tmp_path / "alerts.jsonl"
    server, url = serve_in_background(out)
    try:
        sent = alert.send(report, url)
    finally:
        server.shutdown()
    received = [json.loads(line) for line in out.read_text().splitlines()]
    assert sent is not None and received == [sent]
    assert received[0]["severity"] == "error"  # the stale shipments feed is an error, the rest are warnings
    assert {c["name"] for c in received[0]["checks"]} >= {
        "freshness:raw.logistics_shipments",
        "pos_transaction_line_is_unique",
    }


@pytest.mark.slow
def test_clean_data_raises_no_alarms_and_legacy_matches_dbt(tmp_path):
    """A clean landing zone: every check passes, and the legacy reports equal the dbt marts to the cent."""
    env = {
        **os.environ,
        "RETAIL_DATA_DIR": str(tmp_path / "data"),
        "RETAIL_BUILD_DIR": str(tmp_path / "build"),
        "RETAIL_DBT_TARGET": str(tmp_path / "target"),
        "PYTHONIOENCODING": "utf-8",
    }
    env.pop("RETAIL_WAREHOUSE", None)
    env.pop("RETAIL_RAW_DIR", None)
    proc = subprocess.run(
        [sys.executable, "-m", "retail_ai", "pipeline", "--clean"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-3000:]
    assert "WARN=0 ERROR=0" in proc.stdout
    report = json.loads((tmp_path / "build" / "dq" / "dq_report.json").read_text())
    assert report["planted"] == 0 and report["unexplained"] == []
    assert not [c for c in report["detection_checks"] if c["status"] != "pass"]
    from retail_ai.compare import compare

    diffs = compare(tmp_path / "build" / "legacy", tmp_path / "data" / "warehouse.duckdb")
    assert all(d.identical for d in diffs), [(d.report, d.examples[:2]) for d in diffs if not d.identical]
