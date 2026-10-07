"""Loads the landing zone into the warehouse's `raw` schema, one table per source feed.

Files are loaded as text exactly as delivered (typing and cleaning happen in dbt staging). Files of one
feed are combined by column name, so a feed that gains a column (schema drift) still loads, and the new
column becomes visible to the contract tests instead of silently shifting other columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

FEEDS: dict[str, str] = {
    "erp_materials": "erp/materials.csv",
    "erp_customers": "erp/customers.csv",
    "erp_stores": "erp/stores.csv",
    "erp_fx_rates": "erp/fx_rates.csv",
    "erp_gl_store_takings": "erp/gl_store_takings_*.csv",
    "erp_sales_orders": "erp/sales_orders_*.csv",
    "pos_transactions": "pos/*/pos_*.csv",
    "ecom_orders": "ecommerce/orders_*.csv",
    "ecom_order_lines": "ecommerce/order_lines_*.csv",
    "logistics_shipments": "logistics/shipments_*.csv",
    "mkt_search_ads": "marketing/search_ads_*.csv",
    "mkt_social_ads": "marketing/social_ads_*.csv",
    "mkt_other_channels": "marketing/other_channels_*.csv",
}


@dataclass
class Loaded:
    table: str
    files: int
    rows: int


def ingest(raw: Path, warehouse: Path) -> list[Loaded]:
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    root = raw.resolve().as_posix().rstrip("/") + "/"
    out: list[Loaded] = []
    with duckdb.connect(str(warehouse)) as con:
        con.execute("create schema if not exists raw")
        con.execute("""create or replace table raw._ingest_log (
            feed varchar, source_file varchar, rows bigint, extracted_at timestamp, loaded_at timestamp)""")
        for table, pattern in FEEDS.items():
            glob = (raw / pattern).as_posix()
            con.execute(
                f"""
                create or replace table raw.{table} as
                select * exclude (filename), replace(replace(filename, '\\', '/'), ?, '') as _source_file
                from read_csv(?, all_varchar = true, union_by_name = true, filename = true, header = true)
            """,
                [root, glob],
            )
            con.execute(
                f"""
                insert into raw._ingest_log
                select ?, _source_file, count(*), max(_extracted_at::timestamp), current_timestamp::timestamp
                from raw.{table} group by _source_file
            """,
                [table],
            )
            files, rows = con.execute(f"select count(distinct _source_file), count(*) from raw.{table}").fetchone()  # type: ignore[misc]
            out.append(Loaded(table, int(files), int(rows)))
    return out
