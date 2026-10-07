"""Seeded, reproducible source data for Acme Kitchen Co., with planted failures and their ground truth."""

from __future__ import annotations

from pathlib import Path

from .catalog import SEED
from .plant import plant
from .simulate import Dataset, simulate
from .write import write, write_ground_truth

__all__ = ["Dataset", "generate", "simulate", "plant"]


def generate(
    raw: Path, ground_truth: Path, *, clean: bool = False, seed: int = SEED, late_dir: Path | None = None
) -> dict:
    """Simulates the year, plants the failures (unless `clean`), and writes the landing zone."""
    truth = simulate(seed)
    planted = None if clean else plant(truth)
    summary = write(planted.dataset if planted else truth, raw, planted, late_dir)
    write_ground_truth(ground_truth, planted, summary, seed)
    return {**summary, "failures": len(planted.failures) if planted else 0}
