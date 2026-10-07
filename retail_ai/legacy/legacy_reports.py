# monthly reports script  -  run on the 2nd of every month after the files land
# reads all the csv drops and writes the 4 monthly csvs that go to finance + marketing
#
# NOTE: this is the legacy "before" version that the dbt project replaces. It is kept on purpose, untidy,
# as the reference for the migration: on clean files it gives the same numbers as the dbt marts.
import glob
import os
import sys

import pandas as pd

RAW = "data/raw"
OUT = "build/legacy"
if len(sys.argv) > 1:
    RAW = sys.argv[1]
if len(sys.argv) > 2:
    OUT = sys.argv[2]

fx = {}
mats = None


def load_fx():
    global fx
    df = pd.read_csv(RAW + "/erp/fx_rates.csv", dtype=str)
    for i in range(len(df)):
        d = df.iloc[i]["RATE_DATE"]
        fx[d[0:4] + "-" + d[4:6] + "-" + d[6:8]] = float(df.iloc[i]["RATE"])


def nzd(amount, cur, day):
    if cur == "AUD":
        return amount * fx[day]
    return amount


def main():
    global mats
    load_fx()
    mats = pd.read_csv(RAW + "/erp/materials.csv", dtype={"STD_COST_NZD": float})
    groups = {"CW": "Cookware", "BW": "Bakeware", "KT": "Kitchen Tools", "TW": "Tableware", "FS": "Food Storage"}
    mats["cat"] = mats["MATL_GROUP"].map(groups)
    stores = pd.read_csv(RAW + "/erp/stores.csv")
    store_region = dict(zip(stores.STORE_ID, stores.REGION_CODE))
    cust = pd.read_csv(RAW + "/erp/customers.csv")
    cust_region = dict(zip(cust.CUSTOMER, cust.REGION_CODE))

    # ---- store sales
    pos = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/pos/*/*.csv"))])
    pos["day"] = pos["txn_ts"].str[0:10]
    pos["month"] = pos["txn_ts"].str[0:7]
    pos["rev"] = pos.apply(lambda r: nzd(r["line_total"], r["currency"], r["day"]), axis=1)
    pos = pos.merge(mats[["SKU", "MATERIAL", "STD_COST_NZD", "cat"]], left_on="sku", right_on="SKU")
    pos["cogs"] = pos["STD_COST_NZD"] * pos["quantity"]
    pos["channel"] = "store"
    pos["region"] = pos["store_id"].map(store_region)
    pos["order_id"] = pos["transaction_id"]
    pos["is_sale"] = pos["txn_type"] == "SALE"

    # ---- web sales
    o = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/ecommerce/orders_*.csv"))])
    l = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/ecommerce/order_lines_*.csv"))])
    o = o[o["order_status"] == "completed"]
    web = l.merge(o[["order_id", "order_ts", "ship_region", "currency", "marketing_channel"]], on="order_id")
    web["day"] = web["order_ts"].str[0:10]
    web["month"] = web["order_ts"].str[0:7]
    web["rev"] = web.apply(lambda r: nzd(r["line_total"], r["currency"], r["day"]), axis=1)
    web = web.merge(mats[["SKU", "MATERIAL", "STD_COST_NZD", "cat"]], left_on="sku", right_on="SKU")
    web["cogs"] = web["STD_COST_NZD"] * web["quantity"]
    web["channel"] = "online"
    web["region"] = web["ship_region"]
    web["is_sale"] = True

    # ---- wholesale
    so = pd.concat(
        [
            pd.read_csv(f, dtype={"DOC_DATE": str, "SALES_DOC": str})
            for f in sorted(glob.glob(RAW + "/erp/sales_orders_*.csv"))
        ]
    )
    so["day"] = so["DOC_DATE"].str[0:4] + "-" + so["DOC_DATE"].str[4:6] + "-" + so["DOC_DATE"].str[6:8]
    so["month"] = so["day"].str[0:7]
    so["rev"] = so.apply(lambda r: nzd(r["NET_VALUE"], r["CURRENCY"], r["day"]), axis=1)
    so = so.merge(mats[["MATERIAL", "STD_COST_NZD", "cat"]], on="MATERIAL")
    so["cogs"] = so["STD_COST_NZD"] * so["ORDER_QTY"]
    so["channel"] = "wholesale"
    so["region"] = so["SOLD_TO"].map(cust_region)
    so["order_id"] = so["SALES_DOC"]
    so["quantity"] = so["ORDER_QTY"]
    so["is_sale"] = True

    cols = ["month", "channel", "region", "order_id", "quantity", "rev", "cogs", "cat", "is_sale"]
    allsales = pd.concat([pos[cols], web[cols], so[cols]])
    allsales["gp"] = allsales["rev"] - allsales["cogs"]

    os.makedirs(OUT, exist_ok=True)

    # report 1: monthly sales
    rows = []
    for (m, ch, rg), g in allsales.groupby(["month", "channel", "region"]):
        rows.append(
            {
                "month": m + "-01",
                "sales_channel": ch,
                "region_code": rg,
                "orders": g[g["is_sale"]]["order_id"].nunique(),
                "units": int(g["quantity"].sum()),
                "revenue_nzd": round(g["rev"].sum(), 2),
                "cogs_nzd": round(g["cogs"].sum(), 2),
                "gross_profit_nzd": round(g["gp"].sum(), 2),
            }
        )
    pd.DataFrame(rows).to_csv(OUT + "/monthly_sales.csv", index=False)

    # report 2: category margin
    rows = []
    for (m, cat), g in allsales.groupby(["month", "cat"]):
        r = g["rev"].sum()
        p = g["gp"].sum()
        rows.append(
            {
                "month": m + "-01",
                "product_category": cat,
                "revenue_nzd": round(r, 2),
                "gross_profit_nzd": round(p, 2),
                "gross_margin": round(p / r, 4),
            }
        )
    pd.DataFrame(rows).to_csv(OUT + "/monthly_category_margin.csv", index=False)

    # report 3: marketing (spend from 3 different exports, each one different!!)
    s1 = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/marketing/search_ads_*.csv"))])
    s1["spend"] = s1["cost_micros"] / 1000000
    s1["day"] = s1["date"]
    s1["ch"] = "paid_search"
    s2 = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/marketing/social_ads_*.csv"))])
    s2["spend"] = s2["amount_spent"]
    s2["day"] = s2["day"].str[6:10] + "-" + s2["day"].str[3:5] + "-" + s2["day"].str[0:2]
    s2["ch"] = "paid_social"
    s3 = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/marketing/other_channels_*.csv"))])
    s3["day"] = s3["date"]
    s3["ch"] = s3["channel"]
    sp = pd.concat(
        [
            s1[["day", "ch", "spend", "currency"]],
            s2[["day", "ch", "spend", "currency"]],
            s3[["day", "ch", "spend", "currency"]],
        ]
    )
    sp["nzd"] = sp.apply(lambda r: nzd(r["spend"], r["currency"], r["day"]), axis=1)
    sp["month"] = sp["day"].str[0:7]
    paid = ["paid_search", "paid_social", "display", "email", "affiliate"]
    att = web[web["marketing_channel"].isin(paid)]
    rows = []
    for (m, ch), g in sp.groupby(["month", "ch"]):
        a = att[(att["month"] == m) & (att["marketing_channel"] == ch)]["rev"].sum()
        rows.append(
            {
                "month": m + "-01",
                "marketing_channel": ch,
                "ad_spend_nzd": round(g["nzd"].sum(), 2),
                "attributed_revenue_nzd": round(a, 2),
                "roas": round(a / g["nzd"].sum(), 4),
            }
        )
    pd.DataFrame(rows).to_csv(OUT + "/monthly_marketing.csv", index=False)

    # report 4: delivery
    sh = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(RAW + "/logistics/shipments_*.csv"))])
    sh["ontime"] = sh["delivered_at"].str[0:10] <= sh["promised_date"]
    sh["month"] = sh["promised_date"].str[0:7]
    rows = []
    for (m, ch), g in sh.groupby(["month", "channel"]):
        rows.append(
            {
                "month": m + "-01",
                "sales_channel": ch,
                "shipments": len(g),
                "on_time_shipments": int(g["ontime"].sum()),
                "on_time_rate": round(g["ontime"].sum() / len(g), 4),
            }
        )
    pd.DataFrame(rows).to_csv(OUT + "/monthly_delivery.csv", index=False)
    print("done, reports in", OUT)


if __name__ == "__main__":
    main()
