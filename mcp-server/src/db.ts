// Read-only access to the DuckDB warehouse.
//
// The file is opened in READ_ONLY mode with external access disabled and the configuration locked, so a
// query can neither write, attach another database, nor read files or URLs, whatever SQL reaches it.
import { DuckDBConnection, DuckDBInstance } from "@duckdb/node-api";

export type Row = Record<string, string | number | boolean | null>;

export interface QueryResult {
  columns: string[];
  rows: Row[];
}

export class Warehouse {
  private constructor(
    private readonly instance: DuckDBInstance,
    private readonly connection: DuckDBConnection,
  ) {}

  static async open(path: string): Promise<Warehouse> {
    const instance = await DuckDBInstance.create(path, {
      access_mode: "READ_ONLY",
      enable_external_access: "false",
      autoinstall_known_extensions: "false",
      autoload_known_extensions: "false",
      lock_configuration: "true",
    });
    const connection = await instance.connect();
    return new Warehouse(instance, connection);
  }

  async query(sql: string, params: (string | number)[] = []): Promise<QueryResult> {
    const reader = await this.connection.runAndReadAll(sql, params);
    const columns = reader.columnNames();
    const rows = reader.getRowObjectsJS().map((r) => {
      const out: Row = {};
      for (const [k, v] of Object.entries(r)) out[k] = normalise(v);
      return out;
    });
    return { columns, rows };
  }

  close(): void {
    this.connection.closeSync();
    this.instance.closeSync();
  }
}

function normalise(v: unknown): string | number | boolean | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "bigint") return Number(v);
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "boolean" || typeof v === "string") return v;
  if (v instanceof Date) {
    const iso = v.toISOString();
    return iso.endsWith("T00:00:00.000Z") ? iso.slice(0, 10) : iso.replace(".000Z", "Z");
  }
  return String(v);
}
