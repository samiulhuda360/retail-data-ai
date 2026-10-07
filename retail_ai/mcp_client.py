"""Connects to the TypeScript MCP server over stdio with the official Python MCP client.

    async with metrics_session() as tools:
        catalogue = await tools.call("list_metrics")
        rows = await tools.call("query_metric", {"metrics": ["revenue"], "group_by": ["region"]})

`openai_tools()` converts the server's tool list into the function-calling format chat models expect, so the
agent offers the model exactly the tools the server declares.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import paths

SERVER_ENTRY = paths.MCP_DIR / "dist" / "src" / "index.js"


class ToolError(RuntimeError):
    pass


@dataclass
class MetricsTools:
    session: ClientSession
    tools: list[Any] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)  # every call with its arguments, result size and time

    async def call(self, name: str, arguments: dict | None = None) -> dict:
        started = time.perf_counter()
        res = await self.session.call_tool(name, arguments or {})
        elapsed = time.perf_counter() - started
        text = "\n".join(getattr(c, "text", "") for c in res.content)
        is_error = bool(_attr(res, "is_error", "isError"))
        self.calls.append({"tool": name, "arguments": arguments or {}, "error": is_error, "seconds": round(elapsed, 3)})
        if is_error:
            raise ToolError(text)
        structured = _attr(res, "structured_content", "structuredContent")
        data = structured if structured is not None else json.loads(text)
        return dict(data)

    def openai_tools(self, names: list[str] | None = None) -> list[dict]:
        out = []
        for t in self.tools:
            if names is not None and t.name not in names:
                continue
            schema = dict(_attr(t, "input_schema", "inputSchema") or {"type": "object", "properties": {}})
            schema.pop("$schema", None)
            out.append(
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description or "", "parameters": schema},
                }
            )
        return out


def _attr(obj: Any, *names: str) -> Any:
    """MCP SDK 2.x uses snake_case field names, 1.x camelCase; accept either."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


@asynccontextmanager
async def metrics_session() -> AsyncIterator[MetricsTools]:
    node = shutil.which("node")
    if node is None or not SERVER_ENTRY.exists():
        raise RuntimeError("Build the MCP server first: cd mcp-server && npm ci && npm run build")
    env = {"RETAIL_WAREHOUSE": str(paths.WAREHOUSE), "RETAIL_DBT_TARGET": str(paths.DBT_TARGET)}
    params = StdioServerParameters(command=node, args=[str(SERVER_ENTRY)], env={**os.environ, **env})
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        yield MetricsTools(session=session, tools=list(listed.tools))
