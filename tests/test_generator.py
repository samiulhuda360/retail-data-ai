"""The generator: reproducible, internally consistent, and every planted failure recorded."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from retail_ai.generator import catalog as c
from retail_ai.generator.plant import plant
from retail_ai.generator.simulate import _fx, _materials
from retail_ai.generator.write import write, write_ground_truth


def test_master_data_is_reproducible():
    a, b = np.random.default_rng(7), np.random.default_rng(7)
    pd.testing.assert_frame_equal(_materials(a), _materials(b))
    pd.testing.assert_frame_equal(_fx(a), _fx(b))


def test_finance_ledger_matches_till_takings(dataset):
    pos = dataset.pos.assign(day=dataset.pos["txn_ts"].dt.date)
    takings = pos.groupby(["day", "store_id"])["line_total"].sum().round(2)
    gl = dataset.gl.set_index(["posting_date", "store_id"])["amount_local"]
    assert (takings.sort_index().to_numpy() - gl.sort_index().to_numpy()).max() < 0.01


def test_every_completed_web_order_ships_and_no_cancelled_one_does(dataset):
    done = set(dataset.ecom_orders.loc[dataset.ecom_orders["order_status"] == "completed", "order_id"])
    shipped = set(dataset.shipments.loc[dataset.shipments["channel"] == "online", "order_ref"])
    assert done == shipped
    assert (dataset.shipments["delivered_at"] > dataset.shipments["shipped_at"]).all()


def test_paid_channels_land_near_their_target_roas(dataset):
    orders = dataset.ecom_orders[dataset.ecom_orders["order_status"] == "completed"]
    rev = dataset.ecom_lines.groupby("order_id")["line_total"].sum()
    orders = orders.assign(rev=orders["order_id"].map(rev))
    nz_rev = orders[orders["currency"] == "NZD"].groupby("marketing_channel")["rev"].sum()
    nz_spend = dataset.spend[dataset.spend["currency"] == "NZD"].groupby("marketing_channel")["spend_local"].sum()
    for ch, target in c.TARGET_ROAS.items():
        assert abs(nz_rev[ch] / nz_spend[ch] - target) / target < 0.12


def test_six_failures_are_planted_and_recorded(dataset):
    planted = plant(dataset)
    kinds = [f["kind"] for f in planted.failures]
    assert kinds == [
        "late_file",
        "duplicate_rows",
        "schema_drift",
        "currency_mixup",
        "missing_foreign_key",
        "negative_quantity",
    ]
    d = planted.dataset
    assert len(d.pos) == len(dataset.pos) + planted.failures[1]["rows"]
    negative_sales = d.pos[(d.pos["txn_type"] == "SALE") & (d.pos["quantity"] < 0)]
    assert len(negative_sales) == 1 and not ((dataset.pos["txn_type"] == "SALE") & (dataset.pos["quantity"] < 0)).any()
    assert c.LATE_MATERIAL[0] not in set(d.materials["material_id"])
    assert planted.failures[4]["rows"] > 0
    assert len(dataset.pos) == len(plant(dataset).dataset.pos) - planted.failures[1]["rows"]  # clean copy untouched


def test_landing_zone_layout_and_ground_truth(dataset, tmp_path):
    planted = plant(dataset)
    raw, late = tmp_path / "raw", tmp_path / "late"
    summary = write(planted.dataset, raw, planted, late)
    write_ground_truth(tmp_path / "gt.json", planted, summary, 42)
    assert len(list((raw / "pos").glob("*/*.csv"))) == 7 * 12
    assert not (raw / "logistics" / "shipments_2026-W12.csv").exists()
    assert (late / "logistics" / "shipments_2026-W12.csv").exists()
    jan = pd.read_csv(raw / "ecommerce" / "orders_2026-01.csv", nrows=1)
    dec = pd.read_csv(raw / "ecommerce" / "orders_2025-12.csv", nrows=1)
    assert "promo_code" in jan.columns and "promo_code" not in dec.columns
    s07 = pd.read_csv(raw / "pos" / "S07" / "pos_S07_2026-02.csv")
    assert set(s07["currency"]) == {"NZD"}
    gt = json.loads((tmp_path / "gt.json").read_text())
    assert gt["planted"] and len(gt["failures"]) == 6 and gt["files"] == summary["files"]
