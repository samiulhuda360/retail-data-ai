"""Agents without a model: grounding, scoring, the template report, and the tool loop with a scripted model."""

from __future__ import annotations

import asyncio
import json

import pytest

from retail_ai.agent import analyst
from retail_ai.agent.campaign_report import build, template_report
from retail_ai.agent.grounding import tokens, ungrounded
from retail_ai.eval.reference import Question, load_questions
from retail_ai.eval.scoring import is_correct, normalise_label, parse_number
from retail_ai.llm import ChatResult

FACTS = {
    "week": "2026-W13",
    "totals": {"ad_spend": {"this_week": 3681.12, "previous_week": 3500.0, "change_pct": 5.2}},
    "online": {"on_time": 0.912},
}


def test_grounded_numbers_pass_in_any_display_format():
    text = "Spend was NZD 3,681 (up 5.2%), or 3.7k; on time 91.2% in 2026-W13 from 2026-03-23."
    assert ungrounded(text, FACTS) == []


def test_a_number_not_in_the_results_fails():
    assert ungrounded("Spend was NZD 3,900 and ROAS 4.10.", FACTS) == ["3,900", "4.10"]


def test_dates_and_week_labels_are_not_numbers():
    assert [t.text for t in tokens("Week 2026-W13 (2026-03-23 to 29 March 2026), W13")] == []


def test_scoring_normalises_formats():
    q = Question("x", "dev", "q", {"metric": "gross_margin"})
    assert is_correct(q, 0.4724, "47.24%") and is_correct(q, 0.4724, 47.2) and not is_correct(q, 0.4724, 0.49)
    rev = Question("y", "dev", "q", {"metric": "revenue"})
    assert is_correct(rev, 139973.9, "NZD 139,973.90") and not is_correct(rev, 139973.9, 142080.4)
    assert parse_number("1.2M") == 1.2e6 and parse_number("n/a") is None
    assert normalise_label("Paid Search") == normalise_label("paid_search")
    assert normalise_label("AKL") == normalise_label("Auckland")


def test_question_set_shape():
    qs = load_questions()
    assert len(qs) == 40
    assert sum(q.split == "holdout" for q in qs) == 10
    assert len({q.id for q in qs}) == 40
    assert {q.spec["metric"] for q in qs} >= {
        "revenue",
        "gross_margin",
        "average_order_value",
        "roas",
        "on_time_delivery_rate",
    }


def test_parse_final_answer():
    assert analyst.parse_final('```json\n{"answer": 12.5, "explanation": "x"}\n```')["answer"] == 12.5
    assert analyst.parse_final("no json here") is None


class ScriptedLLM:
    """Plays back a fixed conversation: first a tool call, then the final JSON answer."""

    model = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    def chat(self, messages, tools=None, temperature=0.0):
        self.seen.append(json.loads(json.dumps(messages)))
        return ChatResult(self.replies.pop(0), 100, 20, 0.5, False, self.model)


@pytest.mark.pipeline
def test_agent_tool_loop_uses_the_mcp_server(built_warehouse):
    from retail_ai.mcp_client import metrics_session

    call = {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "query_metric",
            "arguments": json.dumps(
                {
                    "metrics": ["revenue"],
                    "filters": [{"dimension": "sales_channel", "op": "=", "value": "online"}],
                    "start_date": "2025-12-01",
                    "end_date": "2025-12-31",
                }
            ),
        },
    }
    llm = ScriptedLLM(
        [
            {"content": None, "tool_calls": [call]},
            {"content": '{"answer": 139973.903027, "explanation": "online revenue in December"}'},
        ]
    )

    async def go():
        async with metrics_session() as tools:
            return await analyst.answer("How much did the web shop make in December 2025?", tools, llm)

    run = asyncio.run(go())
    assert run.answer == 139973.903027 and run.llm_calls == 2 and not run.error
    tool_msg = llm.seen[1][-1]
    assert tool_msg["role"] == "tool" and "139973.9" in tool_msg["content"]
    assert "select" not in tool_msg["content"].lower()  # the model sees rows, not SQL


@pytest.mark.pipeline
def test_template_campaign_report_is_fully_grounded(built_warehouse):
    result = asyncio.run(build("2026-W13", use_model=False))
    assert result["ungrounded"] == []
    assert result["writer"] == "template" and "# Campaign report, 2026-W13" in result["report"]
    assert template_report(result["facts"]) == result["report"]
