"""The baseline: plain text-to-SQL over the staging layer.

The model gets the staging tables (cleaned, typed and deduplicated, with their documentation), the same metric
descriptions the semantic layer publishes, and the question. It writes one DuckDB query whose single row holds
the answer. A query that fails is sent back once with the error.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from .. import paths
from ..llm import LLM
from .analyst import AgentRun

SYSTEM = """You are a data analyst for Acme Kitchen Co., which sells kitchen and home products through its own
stores (POS), its web shop and wholesale customers (ERP sales orders) in New Zealand and Australia.

Write ONE DuckDB SQL query over the tables below that answers the question. The query must return
exactly one row with one column named answer (a number at full precision, or the label asked for).
- The data covers the financial year FY2026: 2025-04-01 to 2026-03-31. Report amounts in NZD.
- Australian amounts are in AUD; convert with staging.stg_erp__fx_rates (aud_nzd_rate on the same date).
- Return only the SQL in a ```sql code block.

Business definitions:
{glossary}

Tables (schemas staging and reference):
{schema}
"""


ALLOWED = {"staging", "reference"}


@dataclass
class SchemaContext:
    schema: str
    glossary: str


def build_context(warehouse: Path, target: Path) -> SchemaContext:
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    semantic = json.loads((target / "semantic_manifest.json").read_text(encoding="utf-8"))
    docs = {
        n["name"]: n.get("description", "")
        for n in manifest["nodes"].values()
        if n["resource_type"] in ("model", "seed")
    }
    lines = []
    with duckdb.connect(str(warehouse), read_only=True) as con:
        rows = con.execute("""
            select table_schema || '.' || table_name, column_name, data_type
            from information_schema.columns
            where table_schema in ('staging', 'reference')
            order by table_schema desc, table_name, ordinal_position""").fetchall()
    tables: dict[str, list[str]] = {}
    for t, col, typ in rows:
        tables.setdefault(t, []).append(f"{col} {typ.lower()}")
    for t, cols in tables.items():
        doc = " ".join(docs.get(t.split(".", 1)[1], "").split()) or "reference data"
        lines.append(f"{t}: {doc}\n  columns: {', '.join(cols)}")
    glossary = "\n".join(f"- {m['name']}: {m.get('description') or ''}" for m in semantic["metrics"])
    return SchemaContext(schema="\n".join(lines), glossary=glossary)


def extract_sql(text: str) -> str | None:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, flags=re.S | re.I)
    sql = (m.group(1) if m else text).strip().rstrip(";").strip()
    return sql if re.match(r"(?is)^\s*(with|select)\b", sql) else None


def staging_only(con: duckdb.DuckDBPyConnection, sql: str) -> None:
    """Keeps the baseline to the layer it was given: one SELECT over staging and reference tables (or its CTEs)."""
    literal = sql.replace("'", "''")  # the parser needs a constant argument
    tree = json.loads(con.execute(f"select json_serialize_sql('{literal}')").fetchone()[0])  # type: ignore[index]
    if tree.get("error") or len(tree.get("statements", [])) != 1:
        raise duckdb.InvalidInputException("only one SELECT statement is allowed")
    ctes: set[str] = set()
    tables: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            for entry in (node.get("cte_map") or {}).get("map", []):
                ctes.add(str(entry["key"]).lower())
            if node.get("type") == "BASE_TABLE":
                tables.append((str(node.get("schema_name", "")).lower(), str(node.get("table_name", "")).lower()))
            if node.get("type") == "TABLE_FUNCTION":
                raise duckdb.InvalidInputException("table functions are not allowed")
            for v in node.values():
                walk(v)

    walk(tree["statements"])
    for schema, table in tables:
        if schema not in ALLOWED and not (not schema and table in ctes):
            raise duckdb.InvalidInputException(
                f"only staging and reference tables may be used, not {schema or 'main'}.{table}"
            )


def run_sql(sql: str, warehouse: Path) -> list[tuple[Any, ...]]:
    with duckdb.connect(str(warehouse), read_only=True) as con:
        staging_only(con, sql)
        return con.execute(f"select * from ({sql}) as q limit 50").fetchall()


def answer(question: str, llm: LLM, context: SchemaContext, warehouse: Path | None = None) -> AgentRun:
    warehouse = warehouse or paths.WAREHOUSE
    run = AgentRun()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM.format(glossary=context.glossary, schema=context.schema)},
        {"role": "user", "content": question},
    ]
    for attempt in range(2):
        r = llm.chat(messages)
        run.add(r)
        sql = extract_sql(r.content)
        if sql is None:
            run.error = "no SQL in the reply"
            return run
        started = time.perf_counter()
        try:
            rows = run_sql(sql, warehouse)
            run.tool_seconds += time.perf_counter() - started
            run.tool_calls.append({"tool": "sql", "arguments": {"sql": sql}, "error": False})
            run.answer = rows[0][0] if rows else None
            if run.answer is not None:
                run.error = ""
                return run
            run.error = "query returned no rows" if not rows else "query returned NULL"
            if attempt == 0:
                messages += [
                    {"role": "assistant", "content": r.content},
                    {
                        "role": "user",
                        "content": f"The query ran but {run.error[6:]}. Check the filters and "
                        "joins, and return the corrected SQL only.",
                    },
                ]
            continue
        except duckdb.Error as e:
            run.tool_seconds += time.perf_counter() - started
            run.tool_calls.append({"tool": "sql", "arguments": {"sql": sql}, "error": True})
            run.error = f"SQL error: {str(e).splitlines()[0][:200]}"
            if attempt == 0:
                messages += [
                    {"role": "assistant", "content": r.content},
                    {"role": "user", "content": f"The query failed: {e}\nFix it and return the SQL only."},
                ]
    return run
