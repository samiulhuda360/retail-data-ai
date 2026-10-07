#!/usr/bin/env bash
# One-command demo: build the platform from scratch, report data quality, check the semantic layer,
# write the weekly campaign report, and (with AI_API_KEY set) ask the analyst a question.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
retail pipeline                       # generate -> ingest -> freshness + dbt build -> DQ report -> legacy vs dbt
(cd dbt && mf validate-configs)       # MetricFlow validates the semantic layer against the warehouse
retail eval --oracle                  # all 40 questions through the semantic layer vs independent references
retail campaign-report --week 2026-W13
if [ -n "${AI_API_KEY:-}" ]; then
  retail ask "Which marketing channel had the best return on ad spend in December 2025?"
else
  echo "Set AI_API_KEY to try 'retail ask' and the live evaluation (retail eval)."
fi
echo "Data-quality report: build/dq/dq_report.html"
