"""Runs the platform end to end: generate -> ingest -> dbt (freshness, build) -> data-quality report -> alert."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths


@dataclass
class DbtResult:
    command: str
    success: bool
    output: str


def dbt(args: list[str], target_path: Path | None = None, capture: bool = True) -> DbtResult:
    """Runs dbt in a subprocess against the project in dbt/, with the warehouse path from paths.WAREHOUSE."""
    env = {**os.environ, "RETAIL_WAREHOUSE": str(paths.WAREHOUSE), "PYTHONIOENCODING": "utf-8", "NO_COLOR": "1"}
    cmd = [
        sys.executable,
        "-c",
        "from dbt.cli.main import cli; cli()",
        *args,
        "--project-dir",
        str(paths.DBT_DIR),
        "--profiles-dir",
        str(paths.DBT_DIR),
    ]
    cmd += ["--target-path", str(target_path or paths.DBT_TARGET)]
    proc = subprocess.run(
        cmd, cwd=paths.DBT_DIR, env=env, capture_output=capture, text=True, encoding="utf-8", errors="replace"
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return DbtResult(" ".join(["dbt", *args]), proc.returncode == 0, out)


def build(target_path: Path | None = None, echo: bool = True) -> dict[str, DbtResult]:
    """Source freshness first (it writes sources.json), then `dbt build` (models, seeds and every test)."""
    results = {}
    for name, args in (("freshness", ["source", "freshness"]), ("build", ["build"])):
        r = dbt(args, target_path)
        results[name] = r
        if echo:
            print(r.output)
    return results
