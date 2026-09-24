"""A retried tool activity must not pay a second time for a request it already paid.

Each test runs the real ``execute_mcp_tool_activity`` twice with the same request, the
way Temporal retries it: the first attempt pays and is then cancelled (a heartbeat
timeout, a worker shutdown) before its result is returned, and the second must find
the settled payment instead of paying again.
"""

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from agentarea_agents_sdk.tools.base_tool import BaseTool
from agentarea_execution.activities import agent_execution_activities as activities
from agentarea_execution.activities import mcp_payment_httpx, payment_handler
from agentarea_execution.models import MCPToolRequest, McpToolRoute
from temporalio.testing import ActivityEnvironment

PAID_URL = "https://paid.example/mcp"


class FakeWalletService:
    """Wallet service over an in-memory ledger, keyed like the real table."""

    def __init__(self):
        self.wallet = SimpleNamespace(
            id=uuid4(),
            status="active",
            wallet_type="dual",
            x402_config={"network": "eip155:84532"},
            mpp_config={},
        )
        self.records: list[SimpleNamespace] = []

    async def get_wallet(self, agent_id):
        return self.wallet

    async def get_wallet_credentials(self, wallet):
        return {"x402_private_key": "0xkey", "mpp_tempo_key": "tempo-key"}  # pragma: allowlist secret

    async def get_service_budget_remaining(self, agent_id, execution_id):
        return 5.0

    async def record_payment(self, **kwargs):
        record = SimpleNamespace(**kwargs)
        self.records.append(record)
        return record

    async def find_settled_payment(self, idempotency_key):
        for record in self.records:
            if record.idempotency_key == idempotency_key and record.status == "completed":
                return record
        return None


class PaidServer(httpx.AsyncBaseTransport):
    """An x402 resource: 402 until a request carries a payment signature."""

    def __init__(self):
        self.paid_requests = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            self.paid_requests += 1
            return httpx.Response(200, content=b"paid result", request=request)
        return httpx.Response(
            402, headers={"PAYMENT-REQUIRED": "challenge"}, content=b"{}", request=request
        )


class CancelledAfterTool:
    """Cancels the first attempt once the tool has run, as a heartbeat timeout would."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, *, content: str, **_: Any) -> str:
        self.calls += 1
        if self.calls == 1:
            raise asyncio.CancelledError
        return content


@pytest.fixture
def wallet_service():
    return FakeWalletService()


@pytest.fixture
def activity_fns(monkeypatch, wallet_service):
    from agentarea_execution.activities import dependencies

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.get_wallet_service = AsyncMock(return_value=wallet_service)
    ctx.get_mcp_server_instance_service = AsyncMock()
    ctx.get_openapi_connection_service = AsyncMock()
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", MagicMock())
    monkeypatch.setattr(dependencies, "ActivityContext", MagicMock(return_value=ctx))
    monkeypatch.setattr(activities, "_offload_large_activity_output", CancelledAfterTool())
    fns = {fn.__name__: fn for fn in activities.make_agent_activities(MagicMock())}
    return ctx, fns["execute_mcp_tool_activity"]


def _request(**overrides) -> MCPToolRequest:
    fields = {
        "tool_name": "paid_search",
        "tool_args": {"q": "agentarea"},
        "workspace_id": "ws-paid",
        "user_id": "user-1",
        "user_context_data": {"user_id": "user-1", "workspace_id": "ws-paid"},
        "task_id": str(uuid4()),
        "execution_id": "exec-1",
        "tool_call_id": "call_1",
        "agent_id": uuid4(),
    }
    fields.update(overrides)
    return MCPToolRequest(**fields)


async def _run_with_one_retry(fn, request: MCPToolRequest):
    env = ActivityEnvironment()
    with pytest.raises(asyncio.CancelledError):
        await env.run(fn, request)
    return await env.run(fn, request)


@pytest.mark.asyncio
async def test_retried_mcp_call_does_not_pay_again(monkeypatch, activity_fns, wallet_service):
    ctx, execute_mcp_tool_activity = activity_fns
    server = PaidServer()
    signed_payloads = []

    class FakeX402Client:
        async def create_payment_payload(self, payment_required):
            signed_payloads.append(payment_required)
            return {"signed": True}

    class FakeHTTPClient:
        def __init__(self, client):
            pass

        def get_payment_required_response(self, get_header, body):
            return SimpleNamespace(
                accepts=[
                    SimpleNamespace(
                        pay_to="0xrecipient",
                        network="eip155:84532",
                        scheme="exact",
                        get_amount=lambda: "250000",
                    )
                ]
            )

        def encode_payment_signature_header(self, payment_payload):
            return {"PAYMENT-SIGNATURE": "signed"}

    from agentarea_payment.x402_client import X402PaymentClient

    monkeypatch.setattr(X402PaymentClient, "_get_client", lambda self: FakeX402Client())
    monkeypatch.setattr(
        mcp_payment_httpx,
        "import_module",
        lambda name: SimpleNamespace(x402HTTPClient=FakeHTTPClient),
    )
    monkeypatch.setattr(mcp_payment_httpx.httpx, "AsyncHTTPTransport", lambda: server)

    async def execute_tool(instance_id, raw_name, tool_args, httpx_client_factory):
        async with httpx_client_factory() as client:
            response = await client.post(PAID_URL, json=tool_args)
        return {"success": response.status_code == 200, "result": response.text}

    instance = SimpleNamespace(id=uuid4(), name="Paid MCP", json_spec=None)
    mcp_service = ctx.get_mcp_server_instance_service.return_value
    mcp_service.get = AsyncMock(return_value=instance)
    mcp_service.execute_tool = execute_tool

    request = _request(
        mcp_route=McpToolRoute(
            instance_id=str(instance.id), raw_name="search", attachment_ref=str(instance.id)
        ),
        tools=[{"type": "mcp", "name": str(instance.id)}],
    )
    retried = await _run_with_one_retry(execute_mcp_tool_activity, request)

    assert len(signed_payloads) == 1
    assert server.paid_requests == 1
    assert [r.status for r in wallet_service.records] == ["completed"]
    assert retried.success is False
    assert retried.service_cost == 0.0
    assert retried.payment["already_settled"] is True
    assert retried.payment["idempotency_key"] == wallet_service.records[0].idempotency_key


@pytest.mark.asyncio
async def test_retried_http_tool_does_not_pay_again(monkeypatch, activity_fns, wallet_service):
    from agentarea_agents_sdk.tools.openapi_tool import OpenAPIToolFactory

    payments = AsyncMock(
        return_value={
            "success": True,
            "protocol": "mpp",
            "amount_usd": 0.5,
            "recipient": "tempo-recipient",
            "tx_hash": "0xsettled",
            "response_body": "paid result",
            "response_status": 200,
            "error": None,
            "protocol_metadata": {"payment_method": "charge"},
        }
    )
    monkeypatch.setattr(payment_handler, "handle_402_payment", payments)

    class PaidHttpTool(BaseTool):
        def __init__(self, handler):
            self._handler = handler

        @property
        def name(self) -> str:
            return "paid_search"

        @property
        def description(self) -> str:
            return "A paid HTTP operation"

        def get_schema(self) -> dict[str, Any]:
            return {"parameters": {"type": "object", "properties": {}}}

        async def execute(self, **kwargs) -> dict[str, Any]:
            payment = await self._handler(
                url=PAID_URL,
                method="GET",
                response_status=402,
                response_headers={"WWW-Authenticate": "Payment challenge"},
                tool_name=self.name,
            )
            return {"success": bool(payment["success"]), "result": "", "payment": payment}

    async def create_tools(*, payment_handler, **_):
        return [PaidHttpTool(payment_handler)]

    monkeypatch.setattr(OpenAPIToolFactory, "create_tools_from_connection", create_tools)

    request = _request(
        tools=[{"type": "openapi", "name": "paid-api", "settings": {}}],
    )
    retried = await _run_with_one_retry(activity_fns[1], request)

    assert payments.await_count == 1
    assert payments.await_args is not None
    first_key = payments.await_args.kwargs["idempotency_key"]
    assert [(r.status, r.idempotency_key) for r in wallet_service.records] == [
        ("completed", first_key)
    ]
    assert retried.payment["already_settled"] is True
    assert retried.payment["tx_hash"] == "0xsettled"


def test_key_is_stable_per_call_and_distinct_across_calls_and_requests():
    key = payment_handler.payment_idempotency_key
    assert key("task-1:call_1", 0) == key("task-1:call_1", 0)
    assert key("task-1:call_1", 0) != key("task-1:call_1", 1)
    assert key("task-1:call_1", 0) != key("task-2:call_1", 0)


def test_call_ref_without_tool_call_id_uses_the_activity_identity():
    env = ActivityEnvironment()
    env.info = dataclasses.replace(
        env.info, workflow_id="wf-1", workflow_run_id="run-1", activity_id="7"
    )
    request = _request(tool_call_id=None)

    assert env.run(activities._payment_call_ref, request) == "wf-1:run-1:7"
    assert activities._payment_call_ref(_request(task_id="t-1", tool_call_id="c-1")) == "t-1:c-1"
