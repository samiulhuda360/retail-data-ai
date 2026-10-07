// Compiles a metric request into one DuckDB SQL statement, following MetricFlow's semantics for the subset
// used here (simple and ratio metrics, one-hop dimension joins, metric_time at a grain):
//   1. per semantic model, aggregate its measures grouped by the requested dimensions;
//   2. full outer join those aggregates on the dimensions;
//   3. ratio metrics divide numerator by denominator (NULL when the denominator is 0).
// Filter values are bound as parameters; dimension and metric names are checked against the catalogue.
import { Catalogue, GRAINS, type Grain, type MeasureRef, type MetricInfo, type ReachableDimension, type SemanticModel } from "./semantic.js";

export type FilterOp = "=" | "!=" | "in" | "not in" | ">" | ">=" | "<" | "<=";

export interface Filter {
  dimension: string;
  op: FilterOp;
  value: string | number | (string | number)[];
}

export interface MetricRequest {
  metrics: string[];
  group_by?: string[]; // friendly or qualified names; "date" means metric_time at `grain`
  grain?: Grain;
  start_date?: string; // inclusive, YYYY-MM-DD
  end_date?: string; // inclusive, YYYY-MM-DD
  filters?: Filter[];
  order_by?: { field: string; descending?: boolean }[];
  limit?: number;
}

export interface CompiledQuery {
  sql: string;
  params: (string | number)[];
  columns: string[];
}

const AGG: Record<string, (expr: string) => string> = {
  sum: (e) => `sum(${e})`,
  count: (e) => `count(${e})`,
  count_distinct: (e) => `count(distinct ${e})`,
  average: (e) => `avg(${e})`,
  min: (e) => `min(${e})`,
  max: (e) => `max(${e})`,
};
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const OPS: FilterOp[] = ["=", "!=", "in", "not in", ">", ">=", "<", "<="];
export const MAX_LIMIT = 5000;

const ident = (name: string): string => `"${name.replace(/"/g, '""')}"`;

export function compile(catalogue: Catalogue, req: MetricRequest): CompiledQuery {
  if (!req.metrics?.length) throw new Error("Ask for at least one metric.");
  const infos = req.metrics.map((m) => catalogue.get(m));
  const grain: Grain = req.grain ?? "month";
  if (!GRAINS.includes(grain)) throw new Error(`grain must be one of ${GRAINS.join(", ")}`);
  for (const d of [req.start_date, req.end_date]) {
    if (d !== undefined && !DATE_RE.test(d)) throw new Error(`Dates must be YYYY-MM-DD, got '${d}'`);
  }

  // Group-by columns: "date" plus categorical dimensions, validated against every requested metric.
  const groupBy = [...new Set(req.group_by ?? [])];
  const wantsDate = groupBy.includes("date") || groupBy.includes("metric_time");
  const dimNames = groupBy.filter((g) => g !== "date" && g !== "metric_time");
  const dims: ReachableDimension[] = dimNames.map((n) => {
    let found: ReachableDimension | undefined;
    for (const info of infos) found = catalogue.dimension(info, n);
    return found!;
  });
  const filters = (req.filters ?? []).map((f) => {
    if (!OPS.includes(f.op)) throw new Error(`Filter op must be one of ${OPS.join(", ")}`);
    if (f.dimension === "date") throw new Error("Use start_date and end_date to filter by date.");
    let found: ReachableDimension | undefined;
    for (const info of infos) found = catalogue.dimension(info, f.dimension);
    return { ...f, dim: found! };
  });

  // Every measure needed, grouped by the semantic model that owns it.
  const byModel = new Map<string, { model: SemanticModel; measures: MeasureRef[] }>();
  for (const info of infos) {
    for (const ref of info.measures) {
      const entry = byModel.get(ref.model.name) ?? { model: ref.model, measures: [] };
      if (!entry.measures.some((m) => m.measure.name === ref.measure.name)) entry.measures.push(ref);
      byModel.set(ref.model.name, entry);
    }
  }

  const params: (string | number)[] = [];
  const groupCols = [...(wantsDate ? ["date"] : []), ...dims.map((d) => d.alias)];
  const ctes: string[] = [];
  const cteNames: string[] = [];
  let n = 0;
  for (const { model, measures } of byModel.values()) {
    n += 1;
    const reach = catalogue.reachable(model);
    const own = (qualified: string): ReachableDimension => reach.find((r) => r.qualified === qualified)!;
    const joins = new Map<string, string>(); // dimension model name -> alias
    const colFor = (d: ReachableDimension): string => {
      const mine = own(d.qualified);
      if (!mine.via) return `f.${ident(mine.column)}`;
      const key = `${mine.via.model.name}:${mine.via.fk}`;
      if (!joins.has(key)) joins.set(key, `d${joins.size + 1}`);
      return `${joins.get(key)}.${ident(mine.column)}`;
    };
    const timeCol = `f.${ident(measures[0]!.timeColumn)}`;
    const select: string[] = [];
    if (wantsDate) select.push(`cast(date_trunc('${grain}', ${timeCol}) as date) as ${ident("date")}`);
    for (const d of dims) select.push(`${colFor(d)} as ${ident(d.alias)}`);
    for (const ref of measures) {
      const agg = AGG[ref.measure.agg];
      if (!agg) throw new Error(`Aggregation '${ref.measure.agg}' is not supported`);
      select.push(`cast(${agg(`f.${ident("__" + ref.measure.name)}`)} as double) as ${ident(ref.measure.name)}`);
    }
    const where: string[] = [];
    if (req.start_date) {
      params.push(req.start_date);
      where.push(`${timeCol} >= cast($${params.length} as date)`);
    }
    if (req.end_date) {
      params.push(req.end_date);
      where.push(`${timeCol} <= cast($${params.length} as date)`);
    }
    for (const f of filters) {
      const col = colFor(f.dim);
      if (f.op === "in" || f.op === "not in") {
        const values = Array.isArray(f.value) ? f.value : [f.value];
        if (!values.length) throw new Error(`Filter on ${f.dimension} needs at least one value`);
        const marks = values.map((v) => {
          params.push(v);
          return `$${params.length}`;
        });
        where.push(`${col} ${f.op} (${marks.join(", ")})`);
      } else {
        if (Array.isArray(f.value)) throw new Error(`Filter op '${f.op}' takes a single value`);
        params.push(f.value);
        where.push(`${col} ${f.op} $${params.length}`);
      }
    }
    // measure expressions are evaluated on the fact alone, before any join, so bare column names stay unambiguous
    const projected = measures.map((r) => `(${r.measure.expr ?? r.measure.name}) as ${ident("__" + r.measure.name)}`);
    const rel = `(select *, ${projected.join(", ")} from ${ident(model.node_relation.schema_name)}.${ident(model.node_relation.alias)})`;
    const joinSql = [...joins.entries()].map(([key, alias]) => {
      const via = reach.find((r) => r.via && `${r.via.model.name}:${r.via.fk}` === key)!.via!;
      const dimRel = `${ident(via.model.node_relation.schema_name)}.${ident(via.model.node_relation.alias)}`;
      return `left join ${dimRel} as ${alias} on f.${ident(via.fk)} = ${alias}.${ident(via.pk)}`;
    });
    const name = `m${n}_${model.name}`;
    cteNames.push(name);
    ctes.push(
      [
        `${name} as (`,
        `  select ${select.join(",\n         ")}`,
        `  from ${rel} as f`,
        ...joinSql.map((j) => `  ${j}`),
        where.length ? `  where ${where.join("\n    and ")}` : "",
        groupCols.length ? `  group by ${groupCols.map((_, i) => i + 1).join(", ")}` : "",
        `)`,
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }

  // Join the per-model aggregates on the group-by columns, then compute each metric.
  let from = cteNames[0]!;
  for (const name of cteNames.slice(1)) {
    from += groupCols.length
      ? `\nfull outer join ${name} using (${groupCols.map(ident).join(", ")})`
      : `\ncross join ${name}`;
  }
  const metricCols = infos.map((info) => {
    const num = ident(info.numerator);
    const expr = info.denominator ? `${num} / nullif(${ident(info.denominator)}, 0)` : num;
    return `${expr} as ${ident(info.metric.name)}`;
  });
  const columns = [...groupCols, ...infos.map((i) => i.metric.name)];
  const order = (req.order_by ?? []).map((o) => {
    if (!columns.includes(o.field)) throw new Error(`order_by field '${o.field}' must be one of ${columns.join(", ")}`);
    return `${ident(o.field)} ${o.descending ? "desc" : "asc"} nulls last`;
  });
  if (!order.length) order.push(...groupCols.map((c) => `${ident(c)} asc nulls last`));
  const limit = Math.min(Math.max(1, Math.floor(req.limit ?? 1000)), MAX_LIMIT);
  const sql = [
    `with ${ctes.join(",\n")}`,
    `select ${[...groupCols.map(ident), ...metricCols].join(", ")}`,
    `from ${from}`,
    order.length ? `order by ${order.join(", ")}` : "",
    `limit ${limit}`,
  ]
    .filter(Boolean)
    .join("\n");
  return { sql, params, columns };
}

export function describeRequest(req: MetricRequest): string {
  const parts = [`${req.metrics.join(", ")}`];
  if (req.group_by?.length) parts.push(`by ${req.group_by.join(", ")}${req.group_by.includes("date") ? ` (${req.grain ?? "month"})` : ""}`);
  if (req.start_date || req.end_date) parts.push(`from ${req.start_date ?? "start"} to ${req.end_date ?? "end"}`);
  for (const f of req.filters ?? []) parts.push(`where ${f.dimension} ${f.op} ${JSON.stringify(f.value)}`);
  return parts.join(" ");
}

export type { MetricInfo };
