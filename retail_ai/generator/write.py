"""Writes a dataset as the files each source system drops into the landing zone (`data/raw/`).

Each system has its own conventions, as real ones do: the ERP uses upper-case SAP-style names and
yyyymmdd dates, the social ads platform writes dd/mm/yyyy, the search platform reports cost in micros.
Every file carries `_extracted_at`, the UTC time the source system produced it.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from . import catalog as c
from .plant import Planted
from .simulate import Dataset

AS_OF = datetime.fromisoformat(c.AS_OF)


def _month_extract(month: str) -> str:
    y, m = map(int, month.split("-"))
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return f"{nxt} 02:00:00"


def _week_extract(week: str) -> datetime:
    sunday = datetime.strptime(week + "-7", "%G-W%V-%u")
    return sunday + timedelta(days=9, hours=2)


def _save(df: pd.DataFrame, path: Path, extracted: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.assign(_extracted_at=extracted).to_csv(path, index=False, lineterminator="\n")


def _ymd(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.strftime("%Y%m%d")


def write(dataset: Dataset, raw: Path, planted: Planted | None = None, late_dir: Path | None = None) -> dict:
    """Writes the landing zone. With `planted`, the planted failures are applied; returns a file count summary."""
    if raw.exists():
        shutil.rmtree(raw)
    if late_dir is not None and late_dir.exists():
        shutil.rmtree(late_dir)
    d = dataset
    master_ts = f"{AS_OF:%Y-%m-%d} 02:00:00"
    files = 0

    # ERP: master data, FX, finance postings and wholesale sales orders
    m = d.materials
    _save(
        pd.DataFrame(
            {
                "MATERIAL": m["material_id"],
                "SKU": m["sku"],
                "DESCRIPTION": m["description"],
                "MATL_GROUP": m["material_group"],
                "STD_COST_NZD": m["standard_cost_nzd"],
                "LIST_PRICE_NZD": m["list_price_nzd"],
                "LIST_PRICE_AUD": m["list_price_aud"],
                "CREATED_ON": _ymd(m["created_on"]),
            }
        ),
        raw / "erp" / "materials.csv",
        master_ts,
    )
    _save(
        d.customers.rename(
            columns={"customer_id": "CUSTOMER", "customer_name": "NAME", "country": "COUNTRY", "region": "REGION_CODE"}
        )[["CUSTOMER", "NAME", "COUNTRY", "REGION_CODE"]],
        raw / "erp" / "customers.csv",
        master_ts,
    )
    _save(
        d.stores.rename(columns=str.upper).rename(columns={"REGION": "REGION_CODE"}),
        raw / "erp" / "stores.csv",
        master_ts,
    )
    _save(
        pd.DataFrame(
            {"RATE_DATE": _ymd(d.fx["rate_date"]), "FROM_CURR": "AUD", "TO_CURR": "NZD", "RATE": d.fx["rate"]}
        ),
        raw / "erp" / "fx_rates.csv",
        master_ts,
    )
    files += 4

    gl = d.gl.assign(month=pd.to_datetime(d.gl["posting_date"]).dt.strftime("%Y-%m"))
    for month, part in gl.groupby("month"):
        _save(
            pd.DataFrame(
                {
                    "POSTING_DATE": _ymd(part["posting_date"]),
                    "STORE_ID": part["store_id"],
                    "GL_ACCOUNT": "410000",
                    "CURRENCY": part["currency"],
                    "AMOUNT_LOCAL": part["amount_local"],
                    "AMOUNT_NZD": part["amount_nzd"],
                }
            ),
            raw / "erp" / f"gl_store_takings_{month}.csv",
            _month_extract(month),
        )
        files += 1

    w = d.wholesale.assign(month=pd.to_datetime(d.wholesale["doc_date"]).dt.strftime("%Y-%m"))
    for month, part in w.groupby("month"):
        _save(
            pd.DataFrame(
                {
                    "SALES_DOC": part["sales_doc"],
                    "ITEM": part["item"],
                    "DOC_DATE": _ymd(part["doc_date"]),
                    "SOLD_TO": part["sold_to"],
                    "MATERIAL": part["material_id"],
                    "ORDER_QTY": part["order_qty"],
                    "UOM": part["uom"],
                    "NET_PRICE": part["net_price"],
                    "NET_VALUE": part["net_value"],
                    "CURRENCY": part["currency"],
                    "REQ_DLV_DATE": _ymd(part["req_delivery_date"]),
                }
            ),
            raw / "erp" / f"sales_orders_{month}.csv",
            _month_extract(month),
        )
        files += 1

    # POS: one file per store per month
    pos = d.pos.assign(month=d.pos["txn_ts"].dt.strftime("%Y-%m"))
    for (store, month), part in pos.groupby(["store_id", "month"], sort=True):
        _save(part.drop(columns="month"), raw / "pos" / store / f"pos_{store}_{month}.csv", _month_extract(month))
        files += 1

    # E-commerce: orders and order lines, monthly
    orders = d.ecom_orders.assign(month=d.ecom_orders["order_ts"].dt.strftime("%Y-%m"))
    month_of = dict(zip(orders["order_id"], orders["month"], strict=True))
    lines = d.ecom_lines.assign(month=d.ecom_lines["order_id"].map(month_of))
    drift_from = planted.drift_from if planted else None
    for month, part in orders.groupby("month"):
        out = part.drop(columns="month")
        if drift_from is None or month < drift_from:
            out = out.drop(columns="promo_code")
        _save(out, raw / "ecommerce" / f"orders_{month}.csv", _month_extract(month))
        _save(
            lines[lines["month"] == month].drop(columns="month"),
            raw / "ecommerce" / f"order_lines_{month}.csv",
            _month_extract(month),
        )
        files += 2

    # Logistics: the 3PL sends one file per ISO week of dispatch, 9 days after the week ends
    ships = d.shipments.assign(week=d.shipments["shipped_at"].dt.strftime("%G-W%V"))
    withheld = set(planted.withheld_weeks) if planted else set()
    for week, part in ships.groupby("week"):
        extracted = _week_extract(week)
        if extracted > AS_OF:
            continue  # not due yet
        name = f"shipments_{week}.csv"
        if week in withheld:
            if late_dir is not None:
                _save(part.drop(columns="week"), late_dir / "logistics" / name, f"{AS_OF + timedelta(days=2)}")
            continue
        _save(part.drop(columns="week"), raw / "logistics" / name, f"{extracted}")
        files += 1

    # Marketing: three platforms, three export formats, monthly
    sp = d.spend.assign(month=pd.to_datetime(d.spend["spend_date"]).dt.strftime("%Y-%m"))
    region_name = {r.code: r.name for r in c.REGIONS}
    for month, part in sp.groupby("month"):
        ts = _month_extract(month)
        s = part[part["marketing_channel"] == "paid_search"]
        country = s["region"].map(lambda r: c.REGION_BY_CODE[r].country)
        _save(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(s["spend_date"]).dt.strftime("%Y-%m-%d"),
                    "campaign_id": "SRCH-" + country + "-" + s["campaign"].str.replace(" ", "").str[:12].str.upper(),
                    "campaign_name": s["campaign"] + " | " + country,
                    "geo_target": country + "-" + s["region"],
                    "currency": s["currency"],
                    "cost_micros": (s["spend_local"] * 1_000_000).round().astype("int64"),
                    "impressions": s["impressions"],
                    "clicks": s["clicks"],
                }
            ),
            raw / "marketing" / f"search_ads_{month}.csv",
            ts,
        )
        s = part[part["marketing_channel"] == "paid_social"]
        _save(
            pd.DataFrame(
                {
                    "day": pd.to_datetime(s["spend_date"]).dt.strftime("%d/%m/%Y"),
                    "campaign_name": s["campaign"],
                    "region": s["region"].map(region_name),
                    "amount_spent": s["spend_local"],
                    "currency": s["currency"],
                    "reach": s["impressions"],
                    "link_clicks": s["clicks"],
                }
            ),
            raw / "marketing" / f"social_ads_{month}.csv",
            ts,
        )
        s = part[~part["marketing_channel"].isin(["paid_search", "paid_social"])]
        _save(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(s["spend_date"]).dt.strftime("%Y-%m-%d"),
                    "channel": s["marketing_channel"],
                    "region_code": s["region"],
                    "spend": s["spend_local"],
                    "currency": s["currency"],
                }
            ),
            raw / "marketing" / f"other_channels_{month}.csv",
            ts,
        )
        files += 3

    return {"files": files}


def write_ground_truth(path: Path, planted: Planted | None, summary: dict, seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "seed": seed,
        "as_of": c.AS_OF,
        "period": {"start": str(c.START), "end": str(c.END)},
        "planted": planted is not None,
        "files": summary["files"],
        "failures": planted.failures if planted else [],
    }
    path.write_text(json.dumps(body, indent=2, default=str) + "\n", encoding="utf-8")
