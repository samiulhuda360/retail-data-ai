#!/usr/bin/env node
// Command line access to the same tools, for scripts and the parity test:
//   node dist/src/cli.js list
//   node dist/src/cli.js explain roas
//   node dist/src/cli.js query '{"metrics":["revenue"],"group_by":["region"]}'
//   node dist/src/cli.js sql "select count(*) from marts.fct_orders"
import { loadDeps } from "./config.js";
import { explainMetric, listMetrics, queryMetric, runReadonlySql } from "./tools.js";

const [command, arg] = process.argv.slice(2);
const deps = await loadDeps();
try {
  let out: unknown;
  if (command === "list") out = listMetrics(deps.catalogue);
  else if (command === "explain" && arg) out = explainMetric(deps, arg);
  else if (command === "query" && arg) out = await queryMetric(deps, JSON.parse(arg));
  else if (command === "sql" && arg) out = await runReadonlySql(deps, arg);
  else {
    console.error("usage: cli.js list | explain <metric> | query '<json>' | sql '<select>'");
    process.exitCode = 2;
  }
  if (out !== undefined) console.log(JSON.stringify(out, null, 2));
} catch (e) {
  console.error((e as Error).message);
  process.exitCode = 1;
} finally {
  deps.warehouse.close();
}
