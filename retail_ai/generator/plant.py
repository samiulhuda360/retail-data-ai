"""Plants six realistic data failures in a copy of the clean dataset and records each one as ground truth.

Each failure is something that happens in real retail data feeds:

| id  | kind               | what happens                                                                  |
|-----|--------------------|-------------------------------------------------------------------------------|
| F1  | late_file          | the 3PL's shipments file for ISO week 2026-W12 has not arrived by the as-of   |
| F2  | duplicate_rows     | Wellington's POS re-sent 14 Nov 2025, so that day's lines appear twice        |
| F3  | schema_drift       | the e-commerce order export gained a `promo_code` column from January 2026    |
| F4  | currency_mixup     | Melbourne's February 2026 POS file labels Australian dollars as NZD           |
| F5  | missing_foreign_key| wholesale lines order a new material the ERP master export does not contain   |
| F6  | negative_quantity  | a Sydney sale line was keyed with a negative quantity                         |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import catalog as c
from .simulate import Dataset

LATE_WEEK = "2026-W12"
DUPLICATE = ("S03", date(2025, 11, 14))
CURRENCY = ("S07", "2026-02")
NEGATIVE = ("S05", date(2025, 8, 9))
DRIFT_FROM = "2026-01"


@dataclass
class Planted:
    dataset: Dataset
    failures: list[dict] = field(default_factory=list)
    drift_from: str | None = None  # first month whose order export carries the extra column
    withheld_weeks: list[str] = field(default_factory=list)


def plant(clean: Dataset) -> Planted:
    d = Dataset(**{k: (v.copy() if isinstance(v, pd.DataFrame) else v) for k, v in vars(clean).items()})
    failures: list[dict] = []

    # F1: a late file. The week is withheld from the landing zone (write.py saves it to late_arrivals/).
    week_rows = int((d.shipments["shipped_at"].dt.strftime("%G-W%V") == LATE_WEEK).sum())
    failures.append(
        {
            "id": "F1",
            "kind": "late_file",
            "source": "logistics.shipments",
            "where": f"logistics/shipments_{LATE_WEEK}.csv",
            "detail": "The 3PL closes each ISO week 9 days after it ends; the 2026-W12 file was due 2026-03-31 02:00 "
            "and has not arrived by the as-of time.",
            "rows": week_rows,
        }
    )

    # F2: a whole store-day re-sent, so its POS lines are duplicated.
    store, day = DUPLICATE
    dup = d.pos[(d.pos["store_id"] == store) & (d.pos["txn_ts"].dt.date == day)]
    d.pos = pd.concat([d.pos, dup], ignore_index=True)
    failures.append(
        {
            "id": "F2",
            "kind": "duplicate_rows",
            "source": "pos.transactions",
            "where": f"pos/{store}/pos_{store}_{day:%Y-%m}.csv",
            "detail": f"All {store} lines for {day} appear twice.",
            "rows": len(dup),
            "store_id": store,
            "date": str(day),
        }
    )

    # F3: schema drift. The column exists in the clean data; only exports from DRIFT_FROM onwards include it.
    drift_rows = int((d.ecom_orders["order_ts"].dt.strftime("%Y-%m") >= DRIFT_FROM).sum())
    failures.append(
        {
            "id": "F3",
            "kind": "schema_drift",
            "source": "ecommerce.orders",
            "where": f"ecommerce/orders_{DRIFT_FROM}.csv onwards",
            "detail": "The order export added a promo_code column between marketing_channel and currency.",
            "rows": drift_rows,
            "column": "promo_code",
        }
    )

    # F4: a currency mix-up. Amounts stay in AUD but the file says NZD.
    store, month = CURRENCY
    mask = (d.pos["store_id"] == store) & (d.pos["txn_ts"].dt.strftime("%Y-%m") == month)
    d.pos.loc[mask, "currency"] = "NZD"
    failures.append(
        {
            "id": "F4",
            "kind": "currency_mixup",
            "source": "pos.transactions",
            "where": f"pos/{store}/pos_{store}_{month}.csv",
            "detail": f"{store} is an Australian store; its {month} file labels AUD amounts as NZD.",
            "rows": int(mask.sum()),
            "store_id": store,
            "month": month,
        }
    )

    # F5: missing foreign keys. The master export predates the March launch.
    late_id = c.LATE_MATERIAL[0]
    orphan = int((d.wholesale["material_id"] == late_id).sum())
    d.materials = d.materials[d.materials["material_id"] != late_id].reset_index(drop=True)
    failures.append(
        {
            "id": "F5",
            "kind": "missing_foreign_key",
            "source": "erp.sales_orders",
            "where": "erp/sales_orders_2026-03.csv -> erp/materials.csv",
            "detail": f"Wholesale lines order {late_id}, which the material master export does not contain yet.",
            "rows": orphan,
            "material_id": late_id,
        }
    )

    # F6: a negative quantity on a sale line (a keying error at the till).
    store, day = NEGATIVE
    cand = d.pos[
        (d.pos["store_id"] == store)
        & (d.pos["txn_ts"].dt.date == day)
        & (d.pos["txn_type"] == "SALE")
        & (d.pos["quantity"] >= 2)
    ]
    idx = cand.index[0]
    d.pos.loc[idx, "quantity"] = -d.pos.loc[idx, "quantity"]
    d.pos.loc[idx, "line_total"] = -d.pos.loc[idx, "line_total"]
    failures.append(
        {
            "id": "F6",
            "kind": "negative_quantity",
            "source": "pos.transactions",
            "where": f"pos/{store}/pos_{store}_{day:%Y-%m}.csv",
            "detail": "A SALE line has a negative quantity (refunds are recorded as RETURN transactions).",
            "rows": 1,
            "transaction_id": d.pos.loc[idx, "transaction_id"],
            "line_no": int(d.pos.loc[idx, "line_no"]),
        }
    )

    return Planted(dataset=d, failures=failures, drift_from=DRIFT_FROM, withheld_weeks=[LATE_WEEK])
