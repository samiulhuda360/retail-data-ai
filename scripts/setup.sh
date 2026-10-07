#!/usr/bin/env bash
# One-command setup: Python package (with dbt, MetricFlow, DuckDB) and the TypeScript MCP server.
# Run inside a virtual environment, e.g.  python -m venv .venv && source .venv/bin/activate
set -euo pipefail
cd "$(dirname "$0")/.."
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
npm --prefix mcp-server ci
npm --prefix mcp-server run build
echo "setup done. Next: bash scripts/demo.sh"
