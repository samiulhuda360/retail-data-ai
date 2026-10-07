// Upstream lineage of a model from dbt's manifest.json: models, seeds and sources it is built from.
import { existsSync, readFileSync } from "node:fs";

interface ManifestNode {
  name: string;
  resource_type: string;
  alias?: string;
  schema?: string;
  description?: string;
  depends_on?: { nodes?: string[] };
  source_name?: string;
}
interface Manifest {
  nodes: Record<string, ManifestNode>;
  sources: Record<string, ManifestNode>;
}

export class Lineage {
  private constructor(private readonly manifest: Manifest | null) {}

  static fromFile(path: string): Lineage {
    return new Lineage(existsSync(path) ? (JSON.parse(readFileSync(path, "utf8")) as Manifest) : null);
  }

  /** Upstream chain for schema.alias, as "resource_type name" entries in breadth-first order. */
  upstream(schema: string, alias: string): string[] {
    if (!this.manifest) return [];
    const nodes = { ...this.manifest.nodes, ...this.manifest.sources };
    const start = Object.entries(nodes).find(([, n]) => n.schema === schema && (n.alias ?? n.name) === alias);
    if (!start) return [];
    const seen = new Set<string>([start[0]]);
    const out: string[] = [];
    const queue = [...(start[1].depends_on?.nodes ?? [])];
    while (queue.length) {
      const id = queue.shift()!;
      if (seen.has(id)) continue;
      seen.add(id);
      const n = nodes[id];
      if (!n) continue;
      out.push(n.resource_type === "source" ? `source ${n.source_name}.${n.name}` : `${n.resource_type} ${n.name}`);
      queue.push(...(n.depends_on?.nodes ?? []));
    }
    return out;
  }

  description(schema: string, alias: string): string {
    if (!this.manifest) return "";
    const n = Object.values(this.manifest.nodes).find((x) => x.schema === schema && (x.alias ?? x.name) === alias);
    return n?.description ?? "";
  }
}
