"""Alert hook: posts a short JSON summary of firing data-quality checks to a webhook.

The URL comes from `DQ_WEBHOOK_URL` (a chat or incident tool's incoming webhook). `mock_webhook.py` is a
local stand-in that records what it receives, used by the demo and the tests.
"""

from __future__ import annotations

import json
import os
import urllib.request

from .report import DQReport


def payload(report: DQReport) -> dict:
    firing = [c for c in report.detection_checks if c.fired]
    return {
        "source": "acme-retail-data-platform",
        "as_of": report.as_of,
        "severity": "error" if any(c.status in {"error", "fail"} for c in firing) else ("warn" if firing else "ok"),
        "summary": f"{len(firing)} data-quality checks firing; {report.quarantined_lines} till lines quarantined",
        "checks": [{"name": c.name, "status": c.status, "failing_rows": c.failures} for c in firing],
    }


def send(report: DQReport, url: str | None = None, timeout: float = 5.0) -> dict | None:
    """Posts the alert when checks are firing. Returns the payload sent, or None when nothing was sent."""
    url = url or os.getenv("DQ_WEBHOOK_URL")
    body = payload(report)
    if not url or body["severity"] == "ok":
        return None
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL is operator configuration)
        resp.read()
    return body
