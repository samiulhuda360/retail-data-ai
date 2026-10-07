"""Ingestion tolerates schema drift; the legacy script and the comparison work on small inputs."""

from __future__ import annotations

import duckdb

from retail_ai.compare import REPORTS, compare
from retail_ai.ingest import FEEDS, ingest


def test_ingest_combines_files_by_column_name(tmp_path):
    raw = tmp_path / "raw"
    for rel, body in {
        "ecommerce/orders_2025-12.csv": "order_id,currency,_extracted_at\nW-1,NZD,2026-01-01 02:00:00\n",
        "ecommerce/orders_2026-01.csv": (
            "order_id,promo_code,currency,_extracted_at\nW-2,SUMMER15,AUD,2026-02-01 02:00:00\n"
        ),
    }.items():
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_text(body)
    # every other feed gets one empty-but-valid file so the loader has something to read
    for table, pattern in FEEDS.items():
        if table == "ecom_orders":
            continue
        path = raw / pattern.replace("*/", "X/").replace("*", "x")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("id,_extracted_at\n1,2026-01-01 00:00:00\n")
    wh = tmp_path / "w.duckdb"
    loaded = {t.table: t for t in ingest(raw, wh)}
    assert loaded["ecom_orders"].files == 2 and loaded["ecom_orders"].rows == 2
    with duckdb.connect(str(wh)) as con:
        rows = con.execute("select order_id, currency, promo_code from raw.ecom_orders order by 1").fetchall()
        log = con.execute("select count(*) from raw._ingest_log where feed = 'ecom_orders'").fetchone()[0]
    assert rows == [("W-1", "NZD", None), ("W-2", "AUD", "SUMMER15")]  # currency did not shift
    assert log == 2


def test_report_contract_lists_the_same_columns_on_both_sides():
    for name, (model, keys, values) in REPORTS.items():
        assert model.startswith("reporting.rpt_")
        assert "month" in keys and values, name


def test_compare_flags_differences(tmp_path):
    wh = tmp_path / "w.duckdb"
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    with duckdb.connect(str(wh)) as con:
        con.execute("create schema reporting")
        for name, (model, keys, values) in REPORTS.items():
            cols = ", ".join(
                [f"'2025-04-01'::date as {k}" if k == "month" else f"'a' as {k}" for k in keys]
                + [f"1.0 as {v}" for v in values]
            )
            con.execute(f"create table {model} as select {cols}")
            header = ",".join(keys + values)
            row = ",".join(["2025-04-01" if k == "month" else "a" for k in keys] + ["1.0"] * len(values))
            (legacy / f"{name}.csv").write_text(f"{header}\n{row}\n")
        con.execute("update reporting.rpt_monthly_sales set revenue_nzd = 2.0")
    diffs = {d.report: d for d in compare(legacy, wh)}
    assert diffs["monthly_sales"].differing_rows == 1
    assert diffs["monthly_sales"].examples[0]["revenue_nzd"] == {"legacy": 1.0, "dbt": 2.0}
    assert all(diffs[n].identical for n in diffs if n != "monthly_sales")
