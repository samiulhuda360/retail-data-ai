"""The AI analyst: answers business questions through the semantic layer's MCP tools.

The model sees the metric catalogue (from `list_metrics`) and may call `query_metric` and `explain_metric`. It
never writes SQL: dates, filters and groupings go to the semantic layer, which owns the definitions.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ..llm import LLM, ChatResult
from ..mcp_client import MetricsTools, ToolError

AGENT_TOOLS = ["query_metric", "explain_metric", "list_metrics"]
MAX_STEPS = 6

SYSTEM = """You are the data analyst for Acme Kitchen Co., which sells kitchen and home products through its own
stores, its web shop and wholesale customers in New Zealand and Australia.

Answer the question with the metrics tools. Do not guess numbers.
- The data covers the financial year FY2026: 2025-04-01 to 2026-03-31. Dates are inclusive.
- Amounts are in NZD. Ratios (gross_margin, on_time_delivery_rate) are fractions, e.g. 0.58 for 58%.
- Call query_metric with start_date and end_date for the period asked, and one filter per condition in the
  question (region, country, sales_channel, marketing_channel, product_category, carrier).
- Dimension values: region is Auckland, Wellington, Christchurch, Sydney or Melbourne; country is NZ or AU;
  sales_channel is store, online or wholesale; marketing_channel is paid_search, paid_social, display, email,
  affiliate or organic.
- For a "which ..." question, group_by that dimension and compare the rows.
- When the tool result answers the question, reply with only a JSON object:
  {"answer": <number or the dimension value>, "explanation": "<one short sentence>"}
  Give numbers at full precision as returned by the tool (no rounding, no units, no % sign).

Metric catalogue:
"""


@dataclass
class AgentRun:
    answer: Any = None
    explanation: str = ""
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_seconds: float = 0.0
    tool_seconds: float = 0.0
    all_cached: bool = True
    cached_calls: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def latency_s(self) -> float:
        return round(self.llm_seconds + self.tool_seconds, 3)

    def add(self, r: ChatResult) -> None:
        self.llm_calls += 1
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.llm_seconds += r.latency_s
        self.all_cached &= r.cached
        self.cached_calls += int(r.cached)


def catalogue_text(metrics: list[dict]) -> str:
    lines = []
    for m in metrics:
        lines.append(f"- {m['name']}: {m['description']} Dimensions: {', '.join(m['dimensions'])}.")
    return "\n".join(lines)


def parse_final(text: str) -> dict | None:
    """Pulls the JSON object out of the model's final message (tolerates code fences and prose around it)."""
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and "answer" in data else None


def _compact(result: dict) -> str:
    """What the model sees from a tool: rows and columns, not the SQL text (it is in the trace)."""
    slim = {k: v for k, v in result.items() if k not in {"sql", "params", "example_sql", "elapsed_ms"}}
    return json.dumps(slim, default=str)[:6000]


async def answer(question: str, tools: MetricsTools, llm: LLM, catalogue: list[dict] | None = None) -> AgentRun:
    run = AgentRun()
    if catalogue is None:
        catalogue = (await tools.call("list_metrics"))["metrics"]
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM + catalogue_text(catalogue)},
        {"role": "user", "content": question},
    ]
    offered = tools.openai_tools(AGENT_TOOLS)
    for _ in range(MAX_STEPS):
        r = llm.chat(messages, tools=offered)
        run.add(r)
        if not r.tool_calls:
            final = parse_final(r.content)
            if final is None:
                run.error = "final message was not the JSON answer"
                run.explanation = r.content[:300]
            else:
                run.answer, run.explanation = final.get("answer"), str(final.get("explanation", ""))
            return run
        messages.append({"role": "assistant", "content": r.content or None, "tool_calls": r.tool_calls})
        for call in r.tool_calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            started = time.perf_counter()
            try:
                if name not in AGENT_TOOLS:
                    raise ToolError(f"tool {name} is not available")
                content = _compact(await tools.call(name, args))
            except ToolError as e:
                content = f"ERROR: {e}"
            run.tool_seconds += time.perf_counter() - started
            run.tool_calls.append({"tool": name, "arguments": args, "error": content.startswith("ERROR")})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
    run.error = run.error or f"no answer after {MAX_STEPS} steps"
    return run
