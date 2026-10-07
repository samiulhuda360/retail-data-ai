"""Shared fixtures. Tests marked `pipeline` read the warehouse built by `retail pipeline` (CI builds it first)."""

from __future__ import annotations

import pytest

from retail_ai import paths


@pytest.fixture(scope="session")
def built_warehouse():
    if not paths.WAREHOUSE.exists() or not (paths.DBT_TARGET / "run_results.json").exists():
        pytest.skip("no built warehouse: run `retail pipeline` first")
    return paths.WAREHOUSE


@pytest.fixture(scope="session")
def dataset():
    from retail_ai.generator.simulate import simulate

    return simulate()
