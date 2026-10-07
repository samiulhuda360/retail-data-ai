// The semantic layer as dbt defines it: semantic models and metrics from target/semantic_manifest.json
// (MetricFlow's format). This module turns them into a catalogue: for every metric, its measures and the
// dimensions it can be grouped or filtered by.
import { readFileSync } from "node:fs";

export interface Entity {
  name: string;
  type: "primary" | "foreign" | "unique" | "natural";
  expr: string | null;
}
export interface Dimension {
  name: string;
  type: "categorical" | "time";
  expr: string | null;
  description?: string | null;
}
export interface Measure {
  name: string;
  agg: string;
  expr: string | null;
  description?: string | null;
  agg_time_dimension?: string | null;
}
export interface SemanticModel {
  name: string;
  description?: string | null;
  node_relation: { alias: string; schema_name: string; relation_name: string };
  defaults?: { agg_time_dimension?: string | null } | null;
  entities: Entity[];
  dimensions: Dimension[];
  measures: Measure[];
}
interface MetricRef {
  name: string;
}
export interface Metric {
  name: string;
  label?: string | null;
  description?: string | null;
  type: "simple" | "ratio" | "derived" | "cumulative" | "conversion";
  type_params: { measure?: MetricRef | null; numerator?: MetricRef | null; denominator?: MetricRef | null };
}
export interface SemanticManifest {
  semantic_models: SemanticModel[];
  metrics: Metric[];
}

/** Friendly dimension names for agents; each maps to MetricFlow's entity-qualified name. */
export const ALIASES: Record<string, string> = {
  region: "region__region_name",
  country: "region__country",
  product_category: "product__product_category",
  sales_channel: "sales_channel__channel_name",
  marketing_channel: "marketing_channel__channel_name",
  carrier: "shipment__carrier",
};
const QUALIFIED_TO_ALIAS = Object.fromEntries(Object.entries(ALIASES).map(([a, q]) => [q, a]));

export const HEADLINE_METRICS = ["revenue", "gross_margin", "average_order_value", "roas", "on_time_delivery_rate"];
export const GRAINS = ["day", "week", "month", "quarter", "year"] as const;
export type Grain = (typeof GRAINS)[number];

/** A dimension reachable from a semantic model: a local column, or a column of a dimension model one join away. */
export interface ReachableDimension {
  qualified: string; // entity__dimension, as MetricFlow names it
  alias: string; // friendly name used in tool calls and result columns
  column: string; // SQL expression in the owning model
  via: { model: SemanticModel; fk: string; pk: string } | null; // null = column of the fact itself
}

export interface MeasureRef {
  measure: Measure;
  model: SemanticModel;
  timeColumn: string;
}

export interface MetricInfo {
  metric: Metric;
  measures: MeasureRef[];
  /** For ratios: the measure names of the numerator and denominator; for simple metrics, one measure. */
  numerator: string;
  denominator: string | null;
  dimensions: ReachableDimension[];
}

export class Catalogue {
  readonly metrics = new Map<string, MetricInfo>();
  private readonly measureIndex = new Map<string, MeasureRef>();

  constructor(readonly manifest: SemanticManifest) {
    for (const model of manifest.semantic_models) {
      for (const measure of model.measures) {
        const timeDim = measure.agg_time_dimension ?? model.defaults?.agg_time_dimension;
        const dim = model.dimensions.find((d) => d.name === timeDim);
        if (!dim) continue; // measures without a time dimension are not queryable here
        this.measureIndex.set(measure.name, { measure, model, timeColumn: dim.expr ?? dim.name });
      }
    }
    for (const metric of manifest.metrics) {
      const info = this.describe(metric);
      if (info) this.metrics.set(metric.name, info);
    }
  }

  static fromFile(path: string): Catalogue {
    return new Catalogue(JSON.parse(readFileSync(path, "utf8")) as SemanticManifest);
  }

  private simpleMeasure(name: string): MeasureRef | undefined {
    const m = this.manifest.metrics.find((x) => x.name === name);
    const measureName = m?.type === "simple" ? m.type_params.measure?.name : undefined;
    return measureName ? this.measureIndex.get(measureName) : undefined;
  }

  private describe(metric: Metric): MetricInfo | null {
    let parts: MeasureRef[];
    if (metric.type === "simple") {
      const m = metric.type_params.measure?.name ? this.measureIndex.get(metric.type_params.measure.name) : undefined;
      if (!m) return null;
      parts = [m];
    } else if (metric.type === "ratio") {
      const num = metric.type_params.numerator && this.simpleMeasure(metric.type_params.numerator.name);
      const den = metric.type_params.denominator && this.simpleMeasure(metric.type_params.denominator.name);
      if (!num || !den) return null;
      parts = [num, den];
    } else {
      return null; // derived, cumulative and conversion metrics are outside this compiler's scope
    }
    const dimsPerModel = parts.map((p) => this.reachable(p.model));
    const shared = dimsPerModel[0]!.filter((d) => dimsPerModel.every((list) => list.some((x) => x.qualified === d.qualified)));
    return {
      metric,
      measures: parts,
      numerator: parts[0]!.measure.name,
      denominator: parts[1]?.measure.name ?? null,
      dimensions: shared,
    };
  }

  /** Dimensions one join away: the model's own categorical columns and those of models whose primary entity it references. */
  reachable(model: SemanticModel): ReachableDimension[] {
    const out: ReachableDimension[] = [];
    const primary = model.entities.find((e) => e.type === "primary");
    for (const d of model.dimensions) {
      if (d.type !== "categorical" || !primary) continue;
      const qualified = `${primary.name}__${d.name}`;
      out.push({ qualified, alias: QUALIFIED_TO_ALIAS[qualified] ?? qualified, column: d.expr ?? d.name, via: null });
    }
    for (const fk of model.entities.filter((e) => e.type === "foreign")) {
      for (const other of this.manifest.semantic_models) {
        const pk = other.entities.find((e) => e.type === "primary" && e.name === fk.name);
        if (!pk || other === model) continue;
        for (const d of other.dimensions) {
          if (d.type !== "categorical") continue;
          const qualified = `${fk.name}__${d.name}`;
          out.push({
            qualified,
            alias: QUALIFIED_TO_ALIAS[qualified] ?? qualified,
            column: d.expr ?? d.name,
            via: { model: other, fk: fk.expr ?? fk.name, pk: pk.expr ?? pk.name },
          });
        }
      }
    }
    return out;
  }

  get(name: string): MetricInfo {
    const info = this.metrics.get(name);
    if (!info) {
      throw new Error(`Unknown metric '${name}'. Available: ${[...this.metrics.keys()].join(", ")}`);
    }
    return info;
  }

  /** Resolves a friendly or qualified dimension name for a metric, or throws with the valid choices. */
  dimension(info: MetricInfo, name: string): ReachableDimension {
    const qualified = ALIASES[name] ?? name;
    const d = info.dimensions.find((x) => x.qualified === qualified);
    if (!d) {
      const valid = info.dimensions.map((x) => x.alias).join(", ");
      throw new Error(`Dimension '${name}' is not available for metric '${info.metric.name}'. Valid: date, ${valid}`);
    }
    return d;
  }

  formula(info: MetricInfo): string {
    const m = info.metric;
    if (m.type === "ratio") return `${m.type_params.numerator!.name} / ${m.type_params.denominator!.name}`;
    const ref = info.measures[0]!;
    return `${ref.measure.agg}(${ref.measure.expr ?? ref.measure.name}) from ${ref.model.node_relation.schema_name}.${ref.model.node_relation.alias}`;
  }
}
