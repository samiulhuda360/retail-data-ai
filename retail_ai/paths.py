"""Where everything lives. Every path can be moved with an environment variable."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _path(env: str, default: Path) -> Path:
    value = os.getenv(env)
    return Path(value).resolve() if value else default


DATA = _path("RETAIL_DATA_DIR", ROOT / "data")
RAW = _path("RETAIL_RAW_DIR", DATA / "raw")
WAREHOUSE = _path("RETAIL_WAREHOUSE", DATA / "warehouse.duckdb")
GROUND_TRUTH = DATA / "ground_truth.json"
LATE = DATA / "late_arrivals"
DBT_DIR = ROOT / "dbt"
DBT_TARGET = DBT_DIR / "target"
BUILD = _path("RETAIL_BUILD_DIR", ROOT / "build")
MCP_DIR = ROOT / "mcp-server"
EVAL_DIR = ROOT / "eval"
CACHE = _path("RETAIL_CACHE_DIR", ROOT / ".cache")
