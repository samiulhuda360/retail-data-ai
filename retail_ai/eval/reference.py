"""Reference answers, computed with pandas from the generator's clean truth tables.

This is deliberately a separate implementation from the dbt models and the semantic layer: it starts from the
simulated transactions (before any failure is planted) and applies the metric definitions directly. If the
warehouse and this module agree on a question, the pipeline, the cleaning rules and the semantic layer all held.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ..generator import catalog as c
from ..generator.simulate import Dataset, simulate

QUESTIONS = Path(__file__).with_name("questions.yaml")
PAID = set(c.MARKETING_CHANNELS)
REGION_NAME = {r.code: r.name for r in c.REGIONS}
COUNTRY = {r.code: r.country for r in c.REGIONS}


@dataclass
class Question:
    id: str
    split: str
    question: str
    spec: dict[str, Any]

    @property
    def kind(self) -> str:
        return "label" if ("argmax" in self.spec or "argmin" in self.spec) else "number"


def load_questions(path: Path = QUESTIONS) -> list[Question]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]
    out = []
    for q in raw:
        spec = dict(q["spec"])
        for k in ("start", "end"):
            spec[k] = str(spec[k])
        out.append(Question(q["id"], q["split"], q["question"].strip(), spec))
    return out


class Truth:
    """Fact frames built from the clean simulation, with readable dimension values."""

    def __init__(self, d: Dataset):
        fx = dict(zip(d.fx["rate_date"], d.fx["rate"], strict=True))
        mats = d.materials.set_index("sku")
        cost_by_id = d.materials.set_index("material_id")["standard_cost_nzd"]
        group_by_id = d.materials.set_index("material_id")["material_group"]
        store_region = dict(zip(d.stores["store_id"], d.stores["region"], strict=True))
        cust_region = dict(zip(d.customers["customer_id"], d.customers["region"], strict=True))

        def to_nzd(amount: pd.Series, currency: pd.Series, day: pd.Series) -> pd.Series:
            rate = day.map(fx).astype(float)
            return np.where(currency == "AUD", amount * rate, amount)

        pos = d.pos.assign(date=d.pos["txn_ts"].dt.date)
        pos_lines = pd.DataFrame(
            {
                "date": pos["date"],
                "sales_channel": "store",
                "region": pos["store_id"].map(store_region),
                "material_id": pos["sku"].map(mats["material_id"]),
                "quantity": pos["quantity"],
                "revenue": to_nzd(pos["line_total"], pos["currency"], pos["date"]),
                "order_id": pos["transaction_id"],
                "order_type": np.where(pos["txn_type"] == "RETURN", "return", "sale"),
            }
        )
        done = d.ecom_orders[d.ecom_orders["order_status"] == "completed"]
        web = d.ecom_lines.merge(done[["order_id", "order_ts", "ship_region", "currency"]], on="order_id")
        web["date"] = web["order_ts"].dt.date
        web_lines = pd.DataFrame(
            {
                "date": web["date"],
                "sales_channel": "online",
                "region": web["ship_region"],
                "material_id": web["sku"].map(mats["material_id"]),
                "quantity": web["quantity"],
                "revenue": to_nzd(web["line_total"], web["currency"], web["date"]),
                "order_id": web["order_id"],
                "order_type": "sale",
            }
        )
        w = d.wholesale
        ws_lines = pd.DataFrame(
            {
                "date": w["doc_date"],
                "sales_channel": "wholesale",
                "region": w["sold_to"].map(cust_region),
                "material_id": w["material_id"],
                "quantity": w["order_qty"],
                "revenue": to_nzd(w["net_value"], w["currency"], w["doc_date"]),
                "order_id": w["sales_doc"],
                "order_type": "sale",
            }
        )
        lines = pd.concat([pos_lines, web_lines, ws_lines], ignore_index=True)
        lines["cogs"] = lines["material_id"].map(cost_by_id) * lines["quantity"]
        lines["product_category"] = lines["material_id"].map(group_by_id).map(c.CATEGORIES)
        self.lines = self._dims(lines)

        orders = lines.groupby(["order_id", "sales_channel"], as_index=False).agg(
            date=("date", "first"),
            region=("region", "first"),
            order_type=("order_type", "first"),
            revenue=("revenue", "sum"),
        )
        channel = dict(zip(done["order_id"], done["marketing_channel"], strict=True))
        orders["marketing_channel"] = orders["order_id"].map(channel)
        self.orders = self._dims(orders)

        s = d.spend
        self.spend = self._dims(
            pd.DataFrame(
                {
                    "date": s["spend_date"],
                    "marketing_channel": s["marketing_channel"],
                    "region": s["region"],
                    "spend": to_nzd(s["spend_local"], s["currency"], s["spend_date"]),
                }
            )
        )

        sh = d.shipments
        self.shipments = self._dims(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(sh["promised_date"]).dt.date,
                    "sales_channel": sh["channel"],
                    "region": sh["dest_region"],
                    "carrier": sh["carrier"],
                    "on_time": sh["delivered_at"].dt.date <= pd.to_datetime(sh["promised_date"]).dt.date,
                }
            )
        )

    @staticmethod
    def _dims(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["country"] = df["region"].map(COUNTRY)
        df["region"] = df["region"].map(REGION_NAME)
        return df

    # ---- metrics -------------------------------------------------------------------------------
    @staticmethod
    def _slice(df: pd.DataFrame, spec: dict, skip: set[str] | None = None) -> pd.DataFrame:
        start, end = date.fromisoformat(spec["start"]), date.fromisoformat(spec["end"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        for dim, value in (spec.get("filters") or {}).items():
            if skip and dim in skip:
                continue
            df = df[df[dim] == value]
        return df

    def value(self, metric: str, spec: dict) -> float:
        if metric in {"revenue", "gross_margin", "units_sold"}:
            df = self._slice(self.lines, spec)
            if metric == "revenue":
                return float(df["revenue"].sum())
            if metric == "units_sold":
                return float(df["quantity"].sum())
            return float((df["revenue"] - df["cogs"]).sum() / df["revenue"].sum())
        if metric in {"orders", "average_order_value"}:
            df = self._slice(self.orders, spec)
            sales = df[df["order_type"] == "sale"]
            return float(len(sales)) if metric == "orders" else float(sales["revenue"].sum() / len(sales))
        if metric in {"ad_spend", "attributed_revenue", "roas"}:
            spend = float(self._slice(self.spend, spec)["spend"].sum())
            o = self._slice(self.orders, spec)
            attributed = float(o[(o["order_type"] == "sale") & o["marketing_channel"].isin(PAID)]["revenue"].sum())
            return {"ad_spend": spend, "attributed_revenue": attributed, "roas": attributed / spend}[metric]
        if metric == "on_time_delivery_rate":
            return float(self._slice(self.shipments, spec)["on_time"].mean())
        raise ValueError(f"unknown metric {metric}")

    def answer(self, q: Question) -> tuple[Any, dict[str, float] | None]:
        """The reference answer; for label questions also the metric value of every candidate."""
        spec = q.spec
        dim = spec.get("argmax") or spec.get("argmin")
        if not dim:
            return self.value(spec["metric"], spec), None
        frame = {"product_category": self.lines, "carrier": self.shipments, "marketing_channel": self.spend}.get(
            dim, self.lines
        )
        if spec["metric"] in {"average_order_value", "orders"}:
            frame = self.orders
        candidates = sorted(v for v in frame[dim].dropna().unique())
        values = {}
        for v in candidates:
            sub = {**spec, "filters": {**(spec.get("filters") or {}), dim: v}}
            try:
                values[v] = self.value(spec["metric"], sub)
            except ZeroDivisionError:
                continue
        values = {k: v for k, v in values.items() if v == v}  # drop NaN
        pick = max if spec.get("argmax") else min
        return pick(values, key=values.__getitem__), values


def reference_answers(questions: list[Question] | None = None, seed: int = c.SEED) -> dict[str, dict]:
    truth = Truth(simulate(seed))
    out = {}
    for q in questions or load_questions():
        answer, candidates = truth.answer(q)
        out[q.id] = {"answer": answer, "candidates": candidates}
    return out
