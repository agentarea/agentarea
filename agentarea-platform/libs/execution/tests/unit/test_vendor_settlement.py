"""Reading what an Apify run finally cost, from a recorded actor-run answer (ADR-0038 §2.3).

The fetch goes to the URL the catalog declares, with the connection's own credential;
a run still going is not settled, a finished one is its usageTotalUsd, and a run the
vendor has no record of (an MCP passthrough) settles at zero.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agentarea_common.tool_cost import Payer, ToolConnection, parse_cost_model
from agentarea_execution import vendor_settlement

APIFY = {
    "source": "settled",
    "estimate": {"amount": "0.0113", "currency": "USD"},
    "settled": {
        "fetch": {
            "url": "https://api.apify.com/v2/actor-runs/{run_id}",
            "params": {"run_id": "$.runId"},
            "cost": "$.data.usageTotalUsd",
            "currency": "USD",
            "done": {
                "path": "$.data.status",
                "in": ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"],
            },
        }
    },
}
# Trimmed from GET /v2/actor-runs/{id} of an apify~rag-web-browser run.
RUNNING = {"data": {"id": "HG7ML7M8z78YcAPEB", "status": "RUNNING", "usageTotalUsd": 0.004}}
SUCCEEDED = {"data": {"id": "HG7ML7M8z78YcAPEB", "status": "SUCCEEDED", "usageTotalUsd": 0.01062}}


def _line(run_id: str):
    return SimpleNamespace(
        id=uuid4(),
        created_by="runner",
        workspace_id="ws-1",
        subject_id=str(uuid4()),
        subject_name="apify--rag-web-browser",
        evidence={"settle": "vendor", "settle_params": {"run_id": run_id}},
    )


@pytest.fixture
def apify(monkeypatch):
    seen: list[httpx.Request] = []
    answers: dict[str, httpx.Response] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers.get(request.url.path, httpx.Response(404, json={"error": "not found"}))

    connection = ToolConnection(
        "conn",
        "com.apify/apify-mcp-server",
        "apify--rag-web-browser",
        Payer.WORKSPACE,
        parse_cost_model(APIFY),
    )

    async def resolved(ctx, line):
        return connection, {"Authorization": "Bearer apify-token"}

    @asynccontextmanager
    async def context(container, user_context):
        yield SimpleNamespace()

    monkeypatch.setattr(vendor_settlement, "_connection", resolved)
    monkeypatch.setattr(vendor_settlement, "ActivityContext", context)
    monkeypatch.setattr(
        vendor_settlement,
        "safe_async_client",
        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handle), **kw),
    )
    return SimpleNamespace(
        seen=seen, answers=answers, settle=vendor_settlement.make_vendor_settle(None)
    )


async def test_a_running_run_is_not_settled_and_a_finished_one_is_its_usage(apify):
    path = "/v2/actor-runs/HG7ML7M8z78YcAPEB"
    apify.answers[path] = httpx.Response(200, json=RUNNING)
    assert await apify.settle(_line("HG7ML7M8z78YcAPEB")) is None

    apify.answers[path] = httpx.Response(200, json=SUCCEEDED)
    cost = await apify.settle(_line("HG7ML7M8z78YcAPEB"))

    assert (cost.vendor_cost, cost.currency, cost.exact) == (Decimal("0.01062"), "USD", True)
    assert apify.seen[-1].headers["Authorization"] == "Bearer apify-token"
    assert str(apify.seen[-1].url) == "https://api.apify.com/v2/actor-runs/HG7ML7M8z78YcAPEB"


async def test_a_passthrough_with_no_run_settles_at_zero(apify):
    cost = await apify.settle(_line("mcp-passthrough"))

    assert cost.vendor_cost == Decimal(0)
