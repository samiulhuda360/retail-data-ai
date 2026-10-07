// Locations of the warehouse and the dbt artifacts; each can be moved with an environment variable.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Warehouse } from "./db.js";
import { Lineage } from "./lineage.js";
import { Catalogue } from "./semantic.js";
import type { ServerDeps } from "./tools.js";

// dist/src/config.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");

export const paths = {
  warehouse: process.env.RETAIL_WAREHOUSE ?? resolve(ROOT, "data", "warehouse.duckdb"),
  dbtTarget: process.env.RETAIL_DBT_TARGET ?? resolve(ROOT, "dbt", "target"),
};

export async function loadDeps(): Promise<ServerDeps> {
  const catalogue = Catalogue.fromFile(resolve(paths.dbtTarget, "semantic_manifest.json"));
  const lineage = Lineage.fromFile(resolve(paths.dbtTarget, "manifest.json"));
  const warehouse = await Warehouse.open(paths.warehouse);
  return { catalogue, lineage, warehouse };
}
