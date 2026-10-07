#!/usr/bin/env node
// Stdio entry point: `node dist/src/index.js` (an MCP client such as Claude Desktop, an IDE or the
// Python analyst in this repo starts it as a subprocess).
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { loadDeps } from "./config.js";
import { createServer } from "./tools.js";

const deps = await loadDeps();
const server = createServer(deps);
await server.connect(new StdioServerTransport());

const shutdown = async () => {
  await server.close();
  deps.warehouse.close();
  process.exit(0);
};
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
process.stdin.on("close", shutdown);
