"""Simulates one financial year of clean trading for Acme Kitchen Co.

`simulate()` returns the true, clean tables. `plant.py` then breaks copies of them in known ways, and
`write.py` lays them out as the files each source system would drop in the landing zone. Everything is
driven by one seeded random generator, so the same seed always produces byte-identical data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import catalog as c


@dataclass
class Dataset:
    materials: pd.DataFrame
    stores: pd.DataFrame
    customers: pd.DataFrame
    fx: pd.DataFrame
    pos: pd.DataFrame
    gl: pd.DataFrame
    ecom_orders: pd.DataFrame
    ecom_lines: pd.DataFrame
    wholesale: pd.DataFrame
    shipments: pd.DataFrame
    spend: pd.DataFrame
    meta: dict = field(default_factory=dict)


PAYMENTS = ["card", "cash", "mobile"]
PAY_CUM = np.cumsum([0.78, 0.10, 0.12])


def days() -> list[date]:
    return [c.START + timedelta(days=i) for i in range((c.END - c.START).days + 1)]


def _in(day: date, window: tuple[date, date]) -> bool:
    return window[0] <= day <= window[1]


def _materials(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    n = 0
    launches = {
        "Copper Saucepan 20cm": date(2025, 10, 15),
        "Cheese Board Slate": date(2025, 10, 15),
        "Bundt Tin 25cm": date(2025, 10, 15),
        "Insulated Food Flask": date(2025, 10, 15),
    }
    for code, items in c.PRODUCTS.items():
        for i, (desc, price) in enumerate(items):
            n += 1
            created = launches.get(desc, date(2023, 1, 1) + timedelta(days=int(rng.integers(0, 700))))
            rows.append(
                {
                    "material_id": f"MAT-{1000 + n}",
                    "sku": f"AK-{code}-{i + 1:02d}",
                    "description": desc,
                    "material_group": code,
                    "standard_cost_nzd": round(price * c.COST_RATIO[code] * float(rng.uniform(0.9, 1.1)), 2),
                    "list_price_nzd": price,
                    "list_price_aud": round(price * c.AUD_PRICE_FACTOR) - 0.01,
                    "created_on": created,
                }
            )
    mid, sku, desc, code, price, launched = c.LATE_MATERIAL
    rows.append(
        {
            "material_id": mid,
            "sku": sku,
            "description": desc,
            "material_group": code,
            "standard_cost_nzd": round(price * c.COST_RATIO[code], 2),
            "list_price_nzd": price,
            "list_price_aud": round(price * c.AUD_PRICE_FACTOR) - 0.01,
            "created_on": launched,
        }
    )
    df = pd.DataFrame(rows)
    # How often each product sells: a skewed spread, cheaper items sell more often.
    weight = rng.gamma(2.0, 1.0, len(df)) * (60.0 / df["list_price_nzd"]) ** 0.4
    df["_weight"] = weight / weight.sum()
    return df


def _fx(rng: np.random.Generator) -> pd.DataFrame:
    rate = 1.085
    rows = []
    for d in days():
        rate = float(np.clip(rate + rng.normal(0, 0.0025), 1.05, 1.12))
        rows.append({"rate_date": d, "rate": round(rate, 4)})
    return pd.DataFrame(rows)


def _product_probs(materials: pd.DataFrame, day: date, retail: bool = True) -> np.ndarray:
    """Chance of each product being picked on a given day (launched products only, seasonal boosts)."""
    boost = np.array([c.CATEGORY_MONTH_BOOST.get(g, {}).get(day.month, 1.0) for g in materials["material_group"]])
    live = (materials["created_on"] <= day).to_numpy().copy()
    if retail:  # the March launch is sold to wholesale customers only (pre-orders) during this year
        live &= (materials["material_id"] != c.LATE_MATERIAL[0]).to_numpy()
    p = materials["_weight"].to_numpy() * boost * live
    return p / p.sum()


def _discount_pct(rng: np.random.Generator, day: date, online: bool) -> float:
    if _in(day, c.BLACK_FRIDAY):
        return 0.20 if online else (0.25 if rng.random() < 0.6 else 0.0)
    if _in(day, c.BOXING_DAY_SALE):
        return 0.15 if online else (0.20 if rng.random() < 0.5 else 0.0)
    return 0.10 if rng.random() < (0.05 if online else 0.08) else 0.0


def _qty(rng: np.random.Generator) -> int:
    r = rng.random()
    return 1 if r < 0.8 else (2 if r < 0.95 else 3)


def _pos(rng: np.random.Generator, materials: pd.DataFrame) -> pd.DataFrame:
    rows: list[tuple] = []
    mats = materials.reset_index(drop=True)
    skus = mats["sku"].tolist()
    prices = {k: mats[k].astype(float).tolist() for k in ("list_price_nzd", "list_price_aud")}
    for d in days():
        probs = _product_probs(mats, d)
        factor = c.MONTH_FACTOR[d.month] * c.STORE_DOW[d.weekday()]
        if _in(d, c.BLACK_FRIDAY):
            factor *= 1.8
        elif _in(d, c.BOXING_DAY_SALE):
            factor *= 1.3
        for store in c.STORES:
            local = c.currency_of(store.region)
            price_col = "list_price_aud" if local == "AUD" else "list_price_nzd"
            n = int(rng.poisson(store.daily_txns * factor))
            times = np.sort(rng.integers(9 * 3600, 18 * 3600, n))
            for seq, secs in enumerate(times, start=1):
                ts = datetime(d.year, d.month, d.day) + timedelta(seconds=int(secs))
                txn = f"{store.store_id}-{d:%Y%m%d}-{seq:04d}"
                pay = PAYMENTS[int(np.searchsorted(PAY_CUM, rng.random()))]
                if rng.random() < 0.025:  # a refund at the till: one line, negative quantity
                    i = min(int(np.searchsorted(np.cumsum(probs), rng.random())), len(probs) - 1)
                    q = -1 if rng.random() < 0.85 else -2
                    price = prices[price_col][i]
                    rows.append(
                        (store.store_id, txn, 1, ts, "RETURN", skus[i], q, price, 0.0, round(q * price, 2), local, pay)
                    )
                    continue
                k = min(int(rng.geometric(0.6)), 5)
                picks = rng.choice(len(mats), size=k, replace=False, p=probs)
                for line_no, i in enumerate(picks, start=1):
                    q = _qty(rng)
                    price = prices[price_col][int(i)]
                    disc = round(q * price * _discount_pct(rng, d, online=False), 2)
                    rows.append(
                        (
                            store.store_id,
                            txn,
                            line_no,
                            ts,
                            "SALE",
                            skus[int(i)],
                            q,
                            price,
                            disc,
                            round(q * price - disc, 2),
                            local,
                            pay,
                        )
                    )
    cols = [
        "store_id",
        "transaction_id",
        "line_no",
        "txn_ts",
        "txn_type",
        "sku",
        "quantity",
        "unit_price",
        "discount_amount",
        "line_total",
        "currency",
        "payment_method",
    ]
    return pd.DataFrame(rows, columns=cols)


def _gl(pos: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """Finance books each store's daily takings in NZD, converting Australian takings at that day's rate."""
    df = pos.assign(posting_date=pos["txn_ts"].dt.date)
    g = df.groupby(["posting_date", "store_id", "currency"], as_index=False)["line_total"].sum()
    g = g.merge(fx, left_on="posting_date", right_on="rate_date", how="left")
    g["amount_local"] = g["line_total"].round(2)
    g["amount_nzd"] = np.where(g["currency"] == "AUD", (g["line_total"] * g["rate"]).round(2), g["amount_local"])
    return (
        g[["posting_date", "store_id", "currency", "amount_local", "amount_nzd"]]
        .sort_values(["posting_date", "store_id"])
        .reset_index(drop=True)
    )


def _ecommerce(rng: np.random.Generator, materials: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    orders: list[dict] = []
    lines: list[tuple] = []
    mats = materials.reset_index(drop=True)
    skus = mats["sku"].tolist()
    prices = {k: mats[k].astype(float).tolist() for k in ("list_price_nzd", "list_price_aud")}
    ch_names = list(c.ATTRIBUTION_SHARE)
    nz_regions, au_regions = ["AKL", "WLG", "CHC"], ["SYD", "MEL"]
    hour_w = np.array([1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 5, 5, 6, 6, 5, 5, 5, 6, 7, 9, 10, 9, 6, 3], dtype=float)
    hour_w /= hour_w.sum()
    for d in days():
        probs = _product_probs(mats, d)
        lam = 34 * c.MONTH_FACTOR[d.month] * c.ONLINE_DOW[d.weekday()]
        share = np.array([c.ATTRIBUTION_SHARE[k] for k in ch_names])
        if _in(d, c.BLACK_FRIDAY):
            lam *= 2.2
            share = share * np.where(np.array(ch_names) == "email", 1.6, 1.0)
        elif _in(d, c.BOXING_DAY_SALE):
            lam *= 1.5
        share = share / share.sum()
        for _ in range(int(rng.poisson(lam))):
            nz = rng.random() < 0.68
            region = str(rng.choice(nz_regions, p=[0.5, 0.27, 0.23]) if nz else rng.choice(au_regions, p=[0.55, 0.45]))
            currency = "NZD" if nz else "AUD"
            price_col = "list_price_nzd" if nz else "list_price_aud"
            hour = int(rng.choice(24, p=hour_w))
            ts = datetime(d.year, d.month, d.day, hour, int(rng.integers(0, 60)), int(rng.integers(0, 60)))
            pct = _discount_pct(rng, d, online=True)
            promo = (
                "BLACKFRIDAY20"
                if _in(d, c.BLACK_FRIDAY)
                else "SUMMER15"
                if _in(d, c.BOXING_DAY_SALE)
                else "WELCOME10"
                if pct
                else ""
            )
            k = min(int(rng.geometric(0.55)), 5)
            picks = rng.choice(len(mats), size=k, replace=False, p=probs)
            order_lines = []
            for line_no, i in enumerate(picks, start=1):
                q = 1 if rng.random() < 0.85 else 2
                price = prices[price_col][int(i)]
                disc = round(q * price * pct, 2)
                order_lines.append([None, line_no, skus[int(i)], q, price, disc, round(q * price - disc, 2)])
            subtotal = round(sum(ln[3] * ln[4] for ln in order_lines), 2)
            discount = round(sum(ln[5] for ln in order_lines), 2)
            shipping = 0.0 if subtotal - discount >= 100 else 9.95
            orders.append(
                {
                    "order_ts": ts,
                    "customer_id": f"C-{int(rng.integers(10000, 19000))}",
                    "site": "nz" if nz else "au",
                    "ship_region": region,
                    "marketing_channel": str(rng.choice(ch_names, p=share)),
                    "promo_code": promo,
                    "currency": currency,
                    "order_status": "cancelled" if rng.random() < 0.02 else "completed",
                    "items_subtotal": subtotal,
                    "discount_total": discount,
                    "shipping_fee": shipping,
                    "order_total": round(subtotal - discount + shipping, 2),
                    "_lines": order_lines,
                }
            )
    orders.sort(key=lambda o: o["order_ts"])
    for n, o in enumerate(orders, start=1):
        o["order_id"] = f"W-{100000 + n}"
        for ln in o.pop("_lines"):
            ln[0] = o["order_id"]
            lines.append(tuple(ln))
    order_cols = [
        "order_id",
        "order_ts",
        "customer_id",
        "site",
        "ship_region",
        "marketing_channel",
        "promo_code",
        "currency",
        "order_status",
        "items_subtotal",
        "discount_total",
        "shipping_fee",
        "order_total",
    ]
    line_cols = ["order_id", "line_no", "sku", "quantity", "unit_price", "discount_amount", "line_total"]
    return pd.DataFrame(orders)[order_cols], pd.DataFrame(lines, columns=line_cols)


def _wholesale(rng: np.random.Generator, materials: pd.DataFrame) -> pd.DataFrame:
    rows: list[tuple] = []
    mats = materials.reset_index(drop=True)
    mat_ids = mats["material_id"].tolist()
    prices = {k: mats[k].astype(float).tolist() for k in ("list_price_nzd", "list_price_aud")}
    cust_w = rng.gamma(2.0, 1.0, len(c.CUSTOMERS))
    cust_w /= cust_w.sum()
    late_idx = int(mats.index[mats["material_id"] == c.LATE_MATERIAL[0]][0])
    so = 4500010000
    for d in days():
        if d.weekday() >= 5:
            continue
        # retailers buy ahead of the season: their orders follow next month's shopper demand
        lam = 5.5 * c.MONTH_FACTOR[(d.month % 12) + 1]
        probs = _product_probs(mats, d, retail=False)
        probs[late_idx] = 0.0
        probs /= probs.sum()
        for _ in range(int(rng.poisson(lam))):
            so += 1
            cust_id, _name, region = c.CUSTOMERS[int(rng.choice(len(c.CUSTOMERS), p=cust_w))]
            currency = c.currency_of(region)
            price_col = "list_price_aud" if currency == "AUD" else "list_price_nzd"
            req = d + timedelta(days=int(rng.integers(5, 11)))
            picks = list(rng.choice(len(mats), size=int(rng.integers(3, 9)), replace=False, p=probs))
            if d >= c.LATE_MATERIAL[5] and rng.random() < 0.08:
                picks.append(late_idx)  # pre-orders of the March launch
            for item, i in enumerate(picks, start=1):
                q = 6 * int(rng.integers(1, 9))
                price = round(prices[price_col][int(i)] * 0.55, 2)
                rows.append(
                    (
                        str(so),
                        item * 10,
                        d,
                        cust_id,
                        mat_ids[int(i)],
                        q,
                        "EA",
                        price,
                        round(q * price, 2),
                        currency,
                        req,
                    )
                )
    cols = [
        "sales_doc",
        "item",
        "doc_date",
        "sold_to",
        "material_id",
        "order_qty",
        "uom",
        "net_price",
        "net_value",
        "currency",
        "req_delivery_date",
    ]
    return pd.DataFrame(rows, columns=cols)


def _ship_one(
    rng: np.random.Generator,
    country: str,
    order_day: date,
    ship_day: date,
    promised: date,
    peak: bool,
    base_bonus: float = 0.0,
) -> tuple[str, date]:
    carriers = c.CARRIERS[country]
    name, on_time_p = carriers[0] if rng.random() < 0.6 else carriers[1]
    on_time_p = min(0.99, on_time_p + base_bonus) * (0.86 if peak else 1.0)
    slack = (promised - ship_day).days
    if slack >= 0 and rng.random() < on_time_p:
        delivered = promised - timedelta(days=int(rng.integers(0, min(slack, 2) + 1)))
    else:
        late = int(rng.choice([1, 2, 3], p=[0.6, 0.3, 0.1]))
        delivered = max(promised, ship_day) + timedelta(days=late)
    return name, max(delivered, ship_day)


def _shipments(rng: np.random.Generator, orders: pd.DataFrame, wholesale: pd.DataFrame) -> pd.DataFrame:
    sla = {"AKL": 2, "WLG": 3, "CHC": 3, "SYD": 2, "MEL": 3}
    rows = []
    for o in orders[orders["order_status"] == "completed"].itertuples(index=False):
        od = o.order_ts.date()
        country = c.REGION_BY_CODE[o.ship_region].country
        ship_day = od + timedelta(days=int(rng.choice([0, 1, 2], p=[0.55, 0.35, 0.10])))
        promised = od + timedelta(days=sla[o.ship_region])
        peak = date(2025, 12, 1) <= od <= date(2025, 12, 24)
        carrier, delivered = _ship_one(rng, country, od, ship_day, promised, peak)
        rows.append(
            (
                o.order_id,
                "online",
                carrier,
                "Auckland DC" if country == "NZ" else "Sydney DC",
                o.ship_region,
                ship_day,
                promised,
                delivered,
            )
        )
    so = wholesale.groupby("sales_doc", as_index=False).agg(
        doc_date=("doc_date", "first"), sold_to=("sold_to", "first"), req=("req_delivery_date", "first")
    )
    region_of = {cid: reg for cid, _n, reg in c.CUSTOMERS}
    for s in so.itertuples(index=False):
        region = region_of[s.sold_to]
        country = c.REGION_BY_CODE[region].country
        ship_day = max(s.doc_date + timedelta(days=1), s.req - timedelta(days=2))
        peak = date(2025, 11, 15) <= s.req <= date(2025, 12, 20)
        carrier, delivered = _ship_one(rng, country, s.doc_date, ship_day, s.req, peak, base_bonus=0.03)
        rows.append(
            (
                s.sales_doc,
                "wholesale",
                carrier,
                "Auckland DC" if country == "NZ" else "Sydney DC",
                region,
                ship_day,
                s.req,
                delivered,
            )
        )
    df = pd.DataFrame(
        rows,
        columns=[
            "order_ref",
            "channel",
            "carrier",
            "origin_dc",
            "dest_region",
            "ship_day",
            "promised_date",
            "delivered_day",
        ],
    )
    secs_ship = rng.integers(13 * 3600, 18 * 3600, len(df))
    secs_dlv = rng.integers(9 * 3600, 19 * 3600, len(df))
    df["shipped_at"] = pd.to_datetime(df["ship_day"]) + pd.to_timedelta(secs_ship, unit="s")
    df["delivered_at"] = pd.to_datetime(df["delivered_day"]) + pd.to_timedelta(secs_dlv, unit="s")
    df["delivered_at"] = df["delivered_at"].where(
        df["delivered_at"] > df["shipped_at"], df["shipped_at"] + pd.Timedelta(hours=3)
    )
    df = df.sort_values(["shipped_at", "order_ref"]).reset_index(drop=True)
    df.insert(0, "shipment_id", [f"SH-{700000 + i}" for i in range(1, len(df) + 1)])
    df["status"] = "delivered"
    return df.drop(columns=["ship_day", "delivered_day"])


def _spend(rng: np.random.Generator, orders: pd.DataFrame, lines: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """Daily paid-media spend per channel and region, sized so each channel lands near its target ROAS."""
    done = orders[orders["order_status"] == "completed"]
    rev = lines.groupby("order_id", as_index=False)["line_total"].sum()
    o = done.merge(rev, on="order_id")
    o["day"] = o["order_ts"].dt.date
    o = o.merge(fx, left_on="day", right_on="rate_date", how="left")
    o["rev_nzd"] = np.where(o["currency"] == "AUD", o["line_total"] * o["rate"], o["line_total"])
    paid = o[o["marketing_channel"].isin(c.MARKETING_CHANNELS)]
    daily = paid.groupby(["day", "marketing_channel", "ship_region"])["rev_nzd"].sum()
    rate = dict(zip(fx["rate_date"], fx["rate"], strict=True))
    rows = []
    for ch in c.MARKETING_CHANNELS:
        for reg in c.REGIONS:
            series = pd.Series([daily.get((d, ch, reg.code), 0.0) for d in days()], index=days())
            smooth = series.rolling(7, center=True, min_periods=1).mean().clip(lower=5.0)
            noise = rng.lognormal(0.0, 0.15, len(series))
            for (d, value), z in zip(smooth.items(), noise, strict=True):
                nzd = value / c.TARGET_ROAS[ch] * z
                cur = c.currency_of(reg.code)
                local = round(nzd / rate[d], 2) if cur == "AUD" else round(nzd, 2)
                rows.append((d, ch, reg.code, cur, local, c.campaign_for(d)))
    df = pd.DataFrame(
        rows, columns=["spend_date", "marketing_channel", "region", "currency", "spend_local", "campaign"]
    )
    df["impressions"] = (df["spend_local"] * rng.uniform(30, 60, len(df))).round().astype(int)
    df["clicks"] = (df["impressions"] * rng.uniform(0.01, 0.05, len(df))).round().astype(int)
    return df


def simulate(seed: int = c.SEED) -> Dataset:
    rng = np.random.default_rng(seed)
    materials = _materials(rng)
    fx = _fx(rng)
    pos = _pos(rng, materials)
    gl = _gl(pos, fx)
    orders, lines = _ecommerce(rng, materials)
    wholesale = _wholesale(rng, materials)
    shipments = _shipments(rng, orders, wholesale)
    spend = _spend(rng, orders, lines, fx)
    stores = pd.DataFrame(
        [
            {
                "store_id": s.store_id,
                "store_name": s.name,
                "region": s.region,
                "country": c.REGION_BY_CODE[s.region].country,
                "currency": c.currency_of(s.region),
            }
            for s in c.STORES
        ]
    )
    customers = pd.DataFrame(
        [
            {"customer_id": cid, "customer_name": name, "region": reg, "country": c.REGION_BY_CODE[reg].country}
            for cid, name, reg in c.CUSTOMERS
        ]
    )
    return Dataset(
        materials=materials,
        stores=stores,
        customers=customers,
        fx=fx,
        pos=pos,
        gl=gl,
        ecom_orders=orders,
        ecom_lines=lines,
        wholesale=wholesale,
        shipments=shipments,
        spend=spend,
        meta={"seed": seed, "start": str(c.START), "end": str(c.END), "as_of": c.AS_OF},
    )
