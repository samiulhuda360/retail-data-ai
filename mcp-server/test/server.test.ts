// Tests through the official SDK's in-memory client: the same path an MCP client takes, without a subprocess.
// They read the warehouse and dbt artifacts built by `retail pipeline` (CI builds them first).
import assert from "node:assert/strict";
import { after, before, describe, it } from "node:test";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { compile } from "../src/compiler.js";
import { loadDeps } from "../src/config.js";
import type { ServerDeps } from "../src/tools.js";
import { createServer } from "../src/tools.js";

let deps: ServerDeps;
let client: Client;

type Payload = Record<string, any>;

async function call(name: string, args: Record<string, unknown> = {}): Promise<{ data: Payload; error: boolean; text: string }> {
  const res = (await client.callTool({ name, arguments: args })) as {
    content: { type: string; text: string }[];
    structuredContent?: Payload;
    isError?: boolean;
  };
  const text = res.content.map((c) => c.text).join("\n");
  return { data: res.structuredContent ?? {}, error: Boolean(res.isError), text };
}

async function sql(query: string): Promise<Payload[]> {
  const r = await call("run_readonly_sql", { sql: query });
  assert.equal(r.error, false, r.text);
  return r.data.rows as Payload[];
}

const close = (a: number, b: number, tol = 1e-6) => assert.ok(Math.abs(a - b) <= tol * Math.max(1, Math.abs(b)), `${a} != ${b}`);

before(async () => {
  deps = await loadDeps();
  const server = createServer(deps);
  const [clientSide, serverSide] = InMemoryTransport.createLinkedPair();
  await server.connect(serverSide);
  client = new Client({ name: "test", version: "1.0.0" });
  await client.connect(clientSide);
});

after(async () => {
  await client.close();
  deps.warehouse.close();
});

describe("tool discovery", () => {
  it("exposes the four tools", async () => {
    const { tools } = await client.listTools();
    assert.deepEqual(tools.map((t) => t.name).sort(), ["explain_metric", "list_metrics", "query_metric", "run_readonly_sql"]);
  });

  it("lists the headline metrics with their dimensions", async () => {
    const { data } = await call("list_metrics");
    const metrics = data.metrics as Payload[];
    const headline = metrics.filter((m) => m.headline).map((m) => m.name).sort();
    assert.deepEqual(headline, ["average_order_value", "gross_margin", "on_time_delivery_rate", "revenue", "roas"]);
    const byName = Object.fromEntries(metrics.map((m) => [m.name, m.dimensions as string[]]));
    assert.deepEqual(byName.revenue!.sort(), ["country", "date", "product_category", "region", "sales_channel"]);
    assert.deepEqual(byName.roas!.sort(), ["country", "date", "marketing_channel", "region"]);
    assert.ok(byName.on_time_delivery_rate!.includes("carrier"));
    assert.ok(byName.average_order_value!.includes("marketing_channel"));
  });
});

describe("query_metric", () => {
  it("revenue matches the fact table", async () => {
    const { data } = await call("query_metric", { metrics: ["revenue"] });
    const [direct] = await sql("select sum(revenue_nzd) as r from marts.fct_sales_lines");
    close(Number((data.rows as Payload[])[0]!.revenue), Number(direct!.r));
  });

  it("gross margin by category matches a hand-written ratio", async () => {
    const { data } = await call("query_metric", { metrics: ["gross_margin"], group_by: ["product_category"] });
    const direct = await sql(`select product_category, sum(gross_profit_nzd) / sum(case when has_cost then revenue_nzd else 0 end) as gm
                              from marts.fct_sales_lines group by 1`);
    const want = Object.fromEntries(direct.map((r) => [r.product_category, Number(r.gm)]));
    for (const row of data.rows as Payload[]) close(Number(row.gross_margin), want[row.product_category]!);
    assert.equal((data.rows as Payload[]).length, direct.length);
  });

  it("roas joins orders and ad spend through shared dimensions, by quarter and region", async () => {
    const { data } = await call("query_metric", {
      metrics: ["roas", "attributed_revenue", "ad_spend"],
      group_by: ["date", "country"],
      grain: "quarter",
      start_date: "2025-10-01",
      end_date: "2025-12-31",
    });
    const rows = data.rows as Payload[];
    assert.deepEqual(rows.map((r) => [r.date, r.country]), [["2025-10-01", "AU"], ["2025-10-01", "NZ"]]);
    for (const r of rows) close(Number(r.roas), Number(r.attributed_revenue) / Number(r.ad_spend));
  });

  it("filters are bound as parameters, so quotes in a value cannot change the query", async () => {
    const hostile = "Auckland' or 1=1 --";
    const r = await call("query_metric", { metrics: ["revenue"], filters: [{ dimension: "region", op: "=", value: hostile }] });
    assert.equal(r.error, false, r.text);
    assert.equal((r.data.rows as Payload[])[0]!.revenue, null);
    assert.ok(!String(r.data.sql).includes(hostile));
  });

  it("in-filters and ordering work", async () => {
    const { data } = await call("query_metric", {
      metrics: ["orders", "average_order_value"],
      group_by: ["sales_channel"],
      filters: [{ dimension: "sales_channel", op: "in", value: ["store", "online"] }],
      order_by: [{ field: "orders", descending: true }],
    });
    assert.deepEqual((data.rows as Payload[]).map((r) => r.sales_channel), ["store", "online"]);
  });

  it("refuses a dimension the metric cannot be grouped by, naming the valid ones", async () => {
    const r = await call("query_metric", { metrics: ["roas"], group_by: ["product_category"] });
    assert.equal(r.error, true);
    assert.match(r.text, /not available for metric 'roas'.*marketing_channel/);
  });

  it("refuses unknown metrics and malformed dates", async () => {
    assert.match((await call("query_metric", { metrics: ["profit_ish"] })).text, /Unknown metric/);
    assert.match((await call("query_metric", { metrics: ["revenue"], start_date: "1/2/2026" })).text, /YYYY-MM-DD/);
  });
});

describe("explain_metric", () => {
  it("shows the formula, measures, lineage and example SQL", async () => {
    const { data } = await call("explain_metric", { name: "gross_margin" });
    assert.equal(data.formula, "gross_profit / costed_revenue");
    const m = (data.measures as Payload[])[0]!;
    assert.equal(m.model, "marts.fct_sales_lines");
    assert.ok((m.upstream as string[]).includes("source raw.pos_transactions"));
    assert.match(String(data.example_sql), /date_trunc\('month'/);
  });
});

describe("run_readonly_sql guard", () => {
  const rejected: [string, RegExp][] = [
    ["delete from marts.fct_orders", /single SELECT/],
    ["select 1; select 2", /exactly one/],
    ["select * from raw.pos_transactions", /Schema 'raw'/],
    ["select * from staging.stg_ecom__orders", /Schema 'staging'/],
    ["select * from read_csv('data/raw/erp/stores.csv')", /Table functions/],
    ["select * from fct_orders", /Qualify table/],
    ["attach 'other.db' as o", /single SELECT/],
    ["copy (select 1) to 'x.csv'", /single SELECT/],
    ["select getenv('HOME')", /not allowed/],
  ];
  for (const [query, pattern] of rejected) {
    it(`rejects: ${query}`, async () => {
      const r = await call("run_readonly_sql", { sql: query });
      assert.equal(r.error, true);
      assert.match(r.text, pattern);
    });
  }

  it("allows CTEs over the marts and caps the rows", async () => {
    const r = await call("run_readonly_sql", {
      sql: "with o as (select * from marts.fct_orders) select order_id from o",
      limit: 5,
    });
    assert.equal(r.error, false, r.text);
    assert.equal(r.data.row_count, 5);
    assert.deepEqual(r.data.tables, ["marts.fct_orders"]);
  });

  it("the connection itself is read-only even without the guard", async () => {
    await assert.rejects(deps.warehouse.query("create table marts.scratch as select 1 as a"), /read-only|READ_ONLY|read only/i);
  });
});

describe("compiler", () => {
  it("parameterises values and caps the limit", () => {
    const q = compile(deps.catalogue, {
      metrics: ["revenue"],
      filters: [{ dimension: "region", op: "in", value: ["Auckland", "Sydney"] }],
      start_date: "2025-04-01",
      limit: 999999,
    });
    assert.deepEqual(q.params, ["2025-04-01", "Auckland", "Sydney"]);
    assert.ok(!q.sql.includes("Auckland"));
    assert.match(q.sql, /limit 5000$/);
  });

  it("rejects an unknown grain", () => {
    assert.throws(() => compile(deps.catalogue, { metrics: ["revenue"], group_by: ["date"], grain: "decade" as never }), /grain/);
  });
});
