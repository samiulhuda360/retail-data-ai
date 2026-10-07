"""Compares the legacy pandas reports with the dbt reporting marts, row by row.

On clean source files the two must agree to the cent: that is the migration's acceptance test. On files
with planted failures they disagree, and the differences show what the legacy script gets wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

REPORTS: dict[str, tuple[str, list[str], list[str]]] = {
    # legacy file: (dbt model, key columns, value columns)
    "monthly_sales": (
        "reporting.rpt_monthly_sales",
        ["month", "sales_channel", "region_code"],
        ["orders", "units", "revenue_nzd", "cogs_nzd", "gross_profit_nzd"],
    ),
    "monthly_category_margin": (
        "reporting.rpt_monthly_category_margin",
        ["month", "product_category"],
        ["revenue_nzd", "gross_profit_nzd", "gross_margin"],
    ),
    "monthly_marketing": (
        "reporting.rpt_monthly_marketing",
        ["month", "marketing_channel"],
        ["ad_spend_nzd", "attributed_revenue_nzd", "roas"],
    ),
    "monthly_delivery": (
        "reporting.rpt_monthly_delivery",
        ["month", "sales_channel"],
        ["shipments", "on_time_shipments", "on_time_rate"],
    ),
}
TOLERANCE = 0.011  # cents of rounding between pandas floats and SQL decimals


@dataclass
class ReportDiff:
    report: str
    rows_legacy: int
    rows_dbt: int
    matched_rows: int
    differing_rows: int
    only_legacy: int
    only_dbt: int
    examples: list[dict] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return self.differing_rows == 0 and self.only_legacy == 0 and self.only_dbt == 0


def compare(legacy_dir: Path, warehouse: Path, examples: int = 5) -> list[ReportDiff]:
    out = []
    with duckdb.connect(str(warehouse), read_only=True) as con:
        for name, (model, keys, values) in REPORTS.items():
            legacy = pd.read_csv(legacy_dir / f"{name}.csv")
            dbt = con.execute(f"select {', '.join(keys + values)} from {model}").df()
            dbt["month"] = pd.to_datetime(dbt["month"]).dt.strftime("%Y-%m-%d")
            legacy["month"] = legacy["month"].astype(str)
            merged = legacy.merge(dbt, on=keys, how="outer", suffixes=("_legacy", "_dbt"), indicator=True)
            both = merged[merged["_merge"] == "both"]
            differs = pd.Series(False, index=both.index)
            for v in values:
                a = pd.to_numeric(both[f"{v}_legacy"]).fillna(0).astype(float)
                b = pd.to_numeric(both[f"{v}_dbt"]).fillna(0).astype(float)
                differs |= (a - b).abs() > TOLERANCE
            diff_rows = both[differs]
            ex = []
            for _, r in diff_rows.head(examples).iterrows():
                item = {k: r[k] for k in keys}
                for v in values:
                    a, b = r[f"{v}_legacy"], r[f"{v}_dbt"]
                    if abs(float(a or 0) - float(b or 0)) > TOLERANCE:
                        item[v] = {"legacy": float(a), "dbt": float(b)}
                ex.append(item)
            out.append(
                ReportDiff(
                    report=name,
                    rows_legacy=len(legacy),
                    rows_dbt=len(dbt),
                    matched_rows=int(len(both) - len(diff_rows)),
                    differing_rows=int(len(diff_rows)),
                    only_legacy=int((merged["_merge"] == "left_only").sum()),
                    only_dbt=int((merged["_merge"] == "right_only").sum()),
                    examples=ex,
                )
            )
    return out


def to_markdown(diffs: list[ReportDiff]) -> str:
    lines = [
        "| Report | Legacy rows | dbt rows | Identical rows | Differing rows | Only in legacy | Only in dbt |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for d in diffs:
        lines.append(
            f"| {d.report} | {d.rows_legacy} | {d.rows_dbt} | {d.matched_rows} | {d.differing_rows} "
            f"| {d.only_legacy} | {d.only_dbt} |"
        )
    return "\n".join(lines)
