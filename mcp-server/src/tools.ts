// The MCP server: four tools over the governed metrics and the read-only warehouse.
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { compile, describeRequest, type MetricRequest } from "./compiler.js";
import type { Warehouse } from "./db.js";
import { Lineage } from "./lineage.js";
import { Catalogue, GRAINS, HEADLINE_METRICS } from "./semantic.js";
import { checkReadonlySql, SqlRejected } from "./sqlguard.js";

export interface ServerDeps {
  catalogue: Catalogue;
  warehouse: Warehouse;
  lineage: Lineage;
}

const MAX_SQL_ROWS = 200;

type ToolResult = { content: { type: "text"; text: string }[]; structuredContent?: Record<string, unknown>; isError?: boolean };

function ok(data: Record<string, unknown>): ToolResult {
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
}

function fail(message: string): ToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}

export function listMetrics(catalogue: Catalogue) {
  return [...catalogue.metrics.values()].map((info) => ({
    name: info.metric.name,
    label: info.metric.label ?? info.metric.name,
    description: info.metric.description ?? "",
    type: info.metric.type,
    headline: HEADLINE_METRICS.includes(info.metric.name),
    dimensions: ["date", ...info.dimensions.map((d) => d.alias)],
  }));
}

export function explainMetric(deps: ServerDeps, name: string) {
  const { catalogue, lineage } = deps;
  const info = catalogue.get(name);
  const example = compile(catalogue, { metrics: [name], group_by: ["date"], grain: "month" });
  return {
    name,
    label: info.metric.label ?? name,
    description: info.metric.description ?? "",
    type: info.metric.type,
    formula: catalogue.formula(info),
    measures: info.measures.map((m) => ({
      name: m.measure.name,
      aggregation: m.measure.agg,
      expression: m.measure.expr ?? m.measure.name,
      description: m.measure.description ?? "",
      model: `${m.model.node_relation.schema_name}.${m.model.node_relation.alias}`,
      time_dimension: m.timeColumn,
      upstream: lineage.upstream(m.model.node_relation.schema_name, m.model.node_relation.alias),
    })),
    dimensions: ["date", ...info.dimensions.map((d) => d.alias)],
    example_sql: example.sql,
  };
}

export async function queryMetric(deps: ServerDeps, req: MetricRequest) {
  const compiled = compile(deps.catalogue, req);
  const started = performance.now();
  const result = await deps.warehouse.query(compiled.sql, compiled.params);
  return {
    request: describeRequest(req),
    columns: compiled.columns,
    rows: result.rows,
    row_count: result.rows.length,
    sql: compiled.sql,
    params: compiled.params,
    elapsed_ms: Math.round(performance.now() - started),
  };
}

export async function runReadonlySql(deps: ServerDeps, sql: string, limit = MAX_SQL_ROWS) {
  const tables = await checkReadonlySql(deps.warehouse, sql);
  const cap = Math.min(Math.max(1, Math.floor(limit)), MAX_SQL_ROWS);
  const result = await deps.warehouse.query(`select * from (${sql.trim().replace(/;\s*$/, "")}) as q limit ${cap}`);
  return { tables, columns: result.columns, rows: result.rows, row_count: result.rows.length, truncated_at: cap };
}

const filterSchema = z.object({
  dimension: z.string().describe("Dimension name, e.g. region, sales_channel, product_category"),
  op: z.enum(["=", "!=", "in", "not in", ">", ">=", "<", "<="]),
  value: z.union([z.string(), z.number(), z.array(z.union([z.string(), z.number()]))]),
});

export function createServer(deps: ServerDeps): McpServer {
  const server = new McpServer({ name: "retail-metrics", version: "1.0.0" });

  server.registerTool(
    "list_metrics",
    {
      title: "List metrics",
      description:
        "Lists the governed business metrics (revenue, gross_margin, average_order_value, roas, on_time_delivery_rate and their building blocks) with the dimensions each can be grouped or filtered by.",
      inputSchema: {},
    },
    async () => ok({ metrics: listMetrics(deps.catalogue), grains: GRAINS }),
  );

  server.registerTool(
    "explain_metric",
    {
      title: "Explain a metric",
      description: "Shows how a metric is defined: formula, measures, source models, upstream lineage and example SQL.",
      inputSchema: { name: z.string().describe("Metric name from list_metrics") },
    },
    async ({ name }) => {
      try {
        return ok(explainMetric(deps, name));
      } catch (e) {
        return fail((e as Error).message);
      }
    },
  );

  server.registerTool(
    "query_metric",
    {
      title: "Query metrics",
      description:
        "Computes one or more metrics, optionally grouped by date (at a grain) and dimensions, over an inclusive date range, with filters. Amounts are NZD; ratios are fractions (0.58 = 58%).",
      inputSchema: {
        metrics: z.array(z.string()).min(1).describe("Metric names, e.g. ['revenue', 'gross_margin']"),
        group_by: z.array(z.string()).optional().describe("'date' and/or dimensions, e.g. ['date', 'region']"),
        grain: z.enum(GRAINS).optional().describe("Grain for 'date' (default month)"),
        start_date: z.string().optional().describe("Inclusive start date, YYYY-MM-DD"),
        end_date: z.string().optional().describe("Inclusive end date, YYYY-MM-DD"),
        filters: z.array(filterSchema).optional(),
        order_by: z.array(z.object({ field: z.string(), descending: z.boolean().optional() })).optional(),
        limit: z.number().int().positive().optional(),
      },
    },
    async (args) => {
      try {
        return ok(await queryMetric(deps, args as MetricRequest));
      } catch (e) {
        return fail((e as Error).message);
      }
    },
  );

  server.registerTool(
    "run_readonly_sql",
    {
      title: "Run read-only SQL",
      description:
        "Runs one SELECT against the marts and reporting schemas (read-only, at most 200 rows). Prefer query_metric for metrics; use this for detail rows the metrics do not cover.",
      inputSchema: {
        sql: z.string().describe("A single SELECT; tables must be schema-qualified, e.g. marts.fct_orders"),
        limit: z.number().int().positive().max(MAX_SQL_ROWS).optional(),
      },
    },
    async ({ sql, limit }) => {
      try {
        return ok(await runReadonlySql(deps, sql, limit));
      } catch (e) {
        return fail(e instanceof SqlRejected ? `Rejected: ${e.message}` : (e as Error).message);
      }
    },
  );

  return server;
}
