// Guard for run_readonly_sql. DuckDB parses the statement (json_serialize_sql) and the guard walks the tree:
//   - exactly one statement, and it must be a SELECT (DuckDB refuses to serialise anything else);
//   - every table it reads must be in an allow-listed schema, or be a CTE defined in the query;
//   - no table functions (read_csv, glob, ...) and no functions on the deny list.
// The connection itself is read-only with external access disabled, so the guard is the second wall.
import type { Warehouse } from "./db.js";

export const ALLOWED_SCHEMAS = ["marts", "reporting"];
const DENIED_FUNCTIONS = new Set([
  "read_csv", "read_csv_auto", "read_parquet", "read_json", "read_json_auto", "read_text", "read_blob",
  "glob", "query", "query_table", "getenv", "current_setting", "duckdb_settings", "duckdb_secrets",
  "duckdb_extensions", "sniff_csv", "parquet_scan", "parquet_metadata",
]);

export class SqlRejected extends Error {}

interface Node {
  [key: string]: unknown;
}

export async function checkReadonlySql(db: Warehouse, sql: string, schemas = ALLOWED_SCHEMAS): Promise<string[]> {
  if (sql.length > 20_000) throw new SqlRejected("Query is too long (20,000 characters at most).");
  // The parser wants a constant argument, so the text goes in as a literal with its quotes doubled.
  const res = await db.query(`select json_serialize_sql('${sql.replace(/'/g, "''")}') as tree`);
  const tree = JSON.parse(String(res.rows[0]?.tree ?? "{}")) as Node;
  if (tree.error) {
    const msg = String(tree.error_message ?? "could not parse");
    throw new SqlRejected(msg.includes("Only SELECT") ? "Only a single SELECT statement is allowed." : `Rejected: ${msg}`);
  }
  const statements = (tree.statements as Node[]) ?? [];
  if (statements.length !== 1) throw new SqlRejected("Send exactly one SELECT statement.");

  const ctes = new Set<string>();
  const tables: { schema: string; table: string }[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) return node.forEach(walk);
    if (!node || typeof node !== "object") return;
    const n = node as Node;
    if (n.cte_map && typeof n.cte_map === "object") {
      for (const entry of ((n.cte_map as Node).map as Node[]) ?? []) ctes.add(String(entry.key).toLowerCase());
    }
    if (n.type === "BASE_TABLE") {
      tables.push({ schema: String(n.schema_name ?? "").toLowerCase(), table: String(n.table_name ?? "").toLowerCase() });
    }
    if (n.type === "TABLE_FUNCTION") throw new SqlRejected("Table functions are not allowed; query the marts instead.");
    if (n.class === "FUNCTION" && DENIED_FUNCTIONS.has(String(n.function_name).toLowerCase())) {
      throw new SqlRejected(`Function ${String(n.function_name)} is not allowed.`);
    }
    for (const v of Object.values(n)) walk(v);
  };
  walk(statements[0]);

  for (const t of tables) {
    if (!t.schema && ctes.has(t.table)) continue;
    if (!t.schema) throw new SqlRejected(`Qualify table '${t.table}' with its schema (${schemas.join(" or ")}).`);
    if (!schemas.includes(t.schema)) {
      throw new SqlRejected(`Schema '${t.schema}' is not readable here. Allowed: ${schemas.join(", ")}.`);
    }
  }
  return [...new Set(tables.filter((t) => t.schema).map((t) => `${t.schema}.${t.table}`))];
}
