"""Scoring answers against references, and the oracle request each question maps to."""

from __future__ import annotations

import re
from typing import Any

from ..generator import catalog as c
from .reference import Question

RATIO_METRICS = {"gross_margin", "average_order_value", "roas", "on_time_delivery_rate"}
FRACTION_METRICS = {"gross_margin", "on_time_delivery_rate"}
REL_TOL = 0.001  # 0.1% relative
FRACTION_ABS_TOL = 0.001  # 0.1 percentage points

_ALIASES = {r.code.lower(): r.name.lower() for r in c.REGIONS}
_ALIASES.update({"newzealand": "nz", "australia": "au"})


def normalise_label(value: Any) -> str:
    s = re.sub(r"[^a-z0-9]", "", str(value).lower())
    return _ALIASES.get(s, s)


def parse_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    s = str(value).strip().lower().replace(",", "").replace("nzd", "").replace("$", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    x = float(m.group())
    tail = s[m.end() :].strip()
    if tail.startswith("%"):
        x /= 100
    elif tail.startswith(("k", "thousand")):
        x *= 1e3
    elif tail.startswith(("m", "million")):
        x *= 1e6
    return x


def is_correct(q: Question, expected: Any, got: Any) -> bool:
    if got is None:
        return False
    if q.kind == "label":
        return normalise_label(got) == normalise_label(expected)
    x = parse_number(got)
    if x is None:
        return False
    exp = float(expected)
    if q.spec["metric"] in FRACTION_METRICS:
        if abs(x) > 1.5 >= abs(exp):  # answered as a percentage
            x /= 100
        if abs(x - exp) <= FRACTION_ABS_TOL:
            return True
    return abs(x - exp) <= REL_TOL * max(abs(exp), 1e-9)


def oracle_request(q: Question) -> dict:
    """The query_metric call that answers the question exactly (used to validate the question set)."""
    spec = q.spec
    req: dict = {"metrics": [spec["metric"]], "start_date": spec["start"], "end_date": spec["end"]}
    filters = [{"dimension": k, "op": "=", "value": v} for k, v in (spec.get("filters") or {}).items()]
    if filters:
        req["filters"] = filters
    dim = spec.get("argmax") or spec.get("argmin")
    if dim:
        req["group_by"] = [dim]
    return req


def oracle_answer(q: Question, result: dict) -> Any:
    rows = result["rows"]
    metric = q.spec["metric"]
    dim = q.spec.get("argmax") or q.spec.get("argmin")
    if not dim:
        return rows[0][metric] if rows else None
    rows = [r for r in rows if r[metric] is not None and r[dim] is not None]
    pick = max if q.spec.get("argmax") else min
    return pick(rows, key=lambda r: r[metric])[dim] if rows else None
