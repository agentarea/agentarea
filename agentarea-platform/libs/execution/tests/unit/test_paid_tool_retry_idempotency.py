"""A retried tool activity must not pay a second time for a request it already paid.

Each test runs the real ``execute_mcp_tool_activity`` twice with the same request, the
way Temporal retries it: the first attempt pays and is then cancelled (a heartbeat
timeout, a worker shutdown) before its result is returned, and the second must find
the settled payment instead of paying again.
"""

import asyncio
import base64
import dataclasses
import importlib
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx2
import pytest
from agentarea_agents_sdk.tools.base_tool import BaseTool
from agentarea_execution.activities import agent_execution_activities as activities
from agentarea_execution.activities import mcp_payment_httpx, payment_handler
from agentarea_execution.activities.agent import tools as tool_activities
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
        return {
            "x402_private_key": "0xkey",  # pragma: allowlist secret
            "mpp_tempo_key": "tempo-key",  # pragma: allowlist secret
        }

    async def get_service_budget_remaining(self, agent_id, execution_id):
        return Decimal("5")

    async def record_payment(self, **kwargs):
        record = SimpleNamespace(**kwargs)
        self.records.append(record)
        return record

    async def find_settled_payment(self, idempotency_key):
        for record in self.records:
            if record.idempotency_key == idempotency_key and record.status == "completed":
                return record
        return None


class PaidServer(httpx2.AsyncBaseTransport):
    """An x402 resource: 402 until a request carries a payment signature."""

    def __init__(self):
        self.paid_requests = 0

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            self.paid_requests += 1
            return httpx2.Response(200, content=b"paid result", request=request)
        return httpx2.Response(
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


class FakeAudit:
    """Audit trail keyed by event id, as the real insert-once table is."""

    def __init__(self) -> None:
        self.rows: dict[Any, dict[str, Any]] = {}

    async def record_once(self, event_id, action, resource_type, resource_id=None, **fields):
        if event_id in self.rows:
            return False
        self.rows[event_id] = {
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            **fields,
        }
        return True


@pytest.fixture
def wallet_service():
    return FakeWalletService()


@pytest.fixture
def audit():
    return FakeAudit()


@pytest.fixture
def activity_fns(monkeypatch, wallet_service, audit):
    from agentarea_execution.activities import dependencies

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.get_wallet_service = AsyncMock(return_value=wallet_service)
    ctx.get_audit_service = AsyncMock(return_value=audit)
    ctx.get_mcp_server_instance_service = AsyncMock()
    ctx.get_openapi_connection_service = AsyncMock()
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", MagicMock())
    monkeypatch.setattr(dependencies, "ActivityContext", MagicMock(return_value=ctx))
    monkeypatch.setattr(tool_activities, "_offload_large_activity_output", CancelledAfterTool())
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


def _prepare_fake_code_tool(monkeypatch) -> list[str]:
    executed: list[str] = []

    class FakeExecutor:
        def register_tool(self, tool_instance: Any) -> None:
            pass

        async def execute_tool(
            self, *, tool_name: str, tool_args: dict[str, Any], **_: Any
        ) -> dict[str, Any]:
            executed.append(tool_name)
            return {"success": True, "result": "executed"}

    async def offload(**kwargs: Any) -> str:
        return kwargs["content"]

    monkeypatch.setattr(tool_activities, "ToolExecutor", FakeExecutor)
    # Patch the module object the activity imports from (sys.modules), not a dotted
    # path: path resolution walks package attributes, which other suite modules rebind.
    monkeypatch.setattr(
        importlib.import_module("agentarea_agents_sdk.tools.code_tools_loader"),
        "create_code_tool_instance",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(tool_activities, "_offload_large_activity_output", offload)
    return executed


@pytest.mark.asyncio
async def test_policy_approved_code_tool_executes_in_activity(monkeypatch, activity_fns):
    _, execute_mcp_tool_activity = activity_fns
    executed = _prepare_fake_code_tool(monkeypatch)
    request = _request(
        tool_name="example",
        tool_args={},
        tools=[{"type": "code", "name": "agentarea/example"}],
        effective_policy={"approval": {"escalation_rules": ["agentarea/example"]}},
        policy_approval_granted=True,
    )

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, request)

    assert result.success is True
    assert executed == ["example"]


@pytest.mark.asyncio
async def test_activity_rejects_unapproved_policy_rule(monkeypatch, activity_fns, audit):
    _, execute_mcp_tool_activity = activity_fns
    executed = _prepare_fake_code_tool(monkeypatch)
    request = _request(
        tool_name="example",
        tool_args={},
        tools=[{"type": "code", "name": "agentarea/example"}],
        effective_policy={"approval": {"escalation_rules": ["agentarea/example"]}},
    )

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, request)

    assert result.success is False
    assert "approval must be resolved" in (result.error or "")
    assert executed == []
    [row] = audit.rows.values()
    assert row["action"] == "tool.call.denied"
    assert "approval must be resolved" in row["event_metadata"]["reason"]


@pytest.mark.asyncio
async def test_activity_deny_overrides_approval_grant(monkeypatch, activity_fns, audit):
    _, execute_mcp_tool_activity = activity_fns
    executed = _prepare_fake_code_tool(monkeypatch)
    request = _request(
        tool_name="example",
        tool_args={"api_token": "sk-live-secret"},
        tools=[{"type": "code", "name": "agentarea/example"}],
        effective_policy={
            "tools": {"denied": ["agentarea/example"]},
            "approval": {"escalation_rules": ["agentarea/example"]},
        },
        policy_approval_granted=True,
    )

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, request)

    assert result.success is False
    assert "denied by policy" in (result.error or "")
    assert executed == []
    [row] = audit.rows.values()
    assert row["action"] == "tool.call.denied"
    assert (row["resource_type"], row["resource_id"]) == ("task", request.task_id)
    assert (row["actor_type"], row["actor_id"]) == ("agent", str(request.agent_id))
    assert row["event_metadata"]["tool"] == "example"
    assert row["event_metadata"]["requested_by"] == "user-1"
    # The argument's name is auditable; the value the model passed is not.
    assert row["event_metadata"]["argument_keys"] == ["api_token"]
    assert "sk-live-secret" not in json.dumps(row)


@pytest.mark.asyncio
async def test_retried_denial_is_audited_once(monkeypatch, activity_fns, audit):
    _, execute_mcp_tool_activity = activity_fns
    _prepare_fake_code_tool(monkeypatch)
    request = _request(
        tool_name="example",
        tool_args={},
        tools=[{"type": "code", "name": "agentarea/example"}],
        effective_policy={"tools": {"denied": ["agentarea/example"]}},
    )
    env = ActivityEnvironment()

    await env.run(execute_mcp_tool_activity, request)
    await env.run(execute_mcp_tool_activity, request)

    assert len(audit.rows) == 1


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
    monkeypatch.setattr(mcp_payment_httpx.httpx2, "AsyncHTTPTransport", lambda **_kwargs: server)

    async def execute_tool(instance_id, raw_name, tool_args, httpx_client_factory, **_options):
        async with httpx_client_factory() as client:
            response = await client.post(PAID_URL, json=tool_args)
        return {"success": response.status_code == 200, "result": response.text}

    instance = SimpleNamespace(
        id=uuid4(), name="Paid MCP", json_spec=None, server_spec_id="spec", managed_by=None
    )
    mcp_service = ctx.get_mcp_server_instance_service.return_value
    mcp_service.get = AsyncMock(return_value=instance)
    mcp_service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=None)
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
    assert retried.replayed is True


class SettledThenFailedServer(PaidServer):
    """Settles the payment, then fails the paid request itself."""

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if "PAYMENT-SIGNATURE" in request.headers:
            self.paid_requests += 1
            receipt = base64.b64encode(json.dumps({"txHash": "0xsettled"}).encode()).decode()
            return httpx2.Response(
                502, headers={"PAYMENT-RESPONSE": receipt}, content=b"upstream", request=request
            )
        return await super().handle_async_request(request)


@pytest.mark.asyncio
async def test_payment_that_settled_before_the_request_failed_is_spent(
    monkeypatch, activity_fns, wallet_service
):
    ctx, execute_mcp_tool_activity = activity_fns
    server = SettledThenFailedServer()

    class FakeX402Client:
        async def create_payment_payload(self, payment_required):
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
    monkeypatch.setattr(mcp_payment_httpx.httpx2, "AsyncHTTPTransport", lambda **_kwargs: server)

    async def execute_tool(instance_id, raw_name, tool_args, httpx_client_factory, **_options):
        async with httpx_client_factory() as client:
            response = await client.post(PAID_URL, json=tool_args)
        return {"success": response.status_code == 200, "result": response.text}

    instance = SimpleNamespace(
        id=uuid4(), name="Paid MCP", json_spec=None, server_spec_id="spec", managed_by=None
    )
    mcp_service = ctx.get_mcp_server_instance_service.return_value
    mcp_service.get = AsyncMock(return_value=instance)
    mcp_service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=None)
    mcp_service.execute_tool = execute_tool

    request = _request(
        mcp_route=McpToolRoute(
            instance_id=str(instance.id), raw_name="search", attachment_ref=str(instance.id)
        ),
        tools=[{"type": "mcp", "name": str(instance.id)}],
    )
    retried = await _run_with_one_retry(execute_mcp_tool_activity, request)

    assert server.paid_requests == 1
    [record] = wallet_service.records
    assert record.status == "completed"
    assert record.tx_hash == "0xsettled"
    assert record.amount_usd == 0.25
    assert "502" in record.error_message
    assert retried.payment["already_settled"] is True


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
        operation_name = "paid_search"
        connection_id = uuid4()

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

    async def create_tools(*, payment_handler=None, **_):
        return [PaidHttpTool(payment_handler)]

    monkeypatch.setattr(OpenAPIToolFactory, "create_tools_from_connection", create_tools)
    ctx, _ = activity_fns
    connection_service = ctx.get_openapi_connection_service.return_value
    connection_service.catalog_connector = AsyncMock(return_value="connection:paid-api")
    connection_service.get_connection = AsyncMock(
        return_value=SimpleNamespace(
            id=PaidHttpTool.connection_id,
            spec_content={"openapi": "3.0.0", "paths": {}},
            custom_query_params=None,
            managed_by=None,
            registry_item_id=None,
        )
    )

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
    assert retried.replayed is True


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

    assert env.run(tool_activities._payment_call_ref, request) == "wf-1:run-1:7"
    assert (
        tool_activities._payment_call_ref(_request(task_id="t-1", tool_call_id="c-1")) == "t-1:c-1"
    )


GATEWAY_ID = "9a0c6d8e-0000-4000-8000-000000000001"
YANDEX = {
    "name": "ru.yandex/search-api",
    "metadata": {
        "agentarea:payers": ["workspace", "platform"],
        "agentarea:cost": {
            "tools": {
                "yandex_search": {
                    "source": "rate",
                    "unit": "request",
                    "rate": {"amount": "0.488", "currency": "RUB"},
                }
            }
        },
    },
}


class GatewayService:
    """A connection made from a catalog entry that declares what its tool costs."""

    def __init__(self, managed_by="platform"):
        self.calls: list[str] = []
        self.instance = SimpleNamespace(
            id=GATEWAY_ID,
            name="Yandex Search",
            json_spec={},
            server_spec_id="spec-yandex",
            managed_by=managed_by,
        )
        server = SimpleNamespace(json_spec=YANDEX)
        self.mcp_server_repository = SimpleNamespace(
            get_server_by_id=AsyncMock(return_value=server)
        )

    async def get(self, instance_id):
        return self.instance

    async def execute_tool(
        self, instance_id, raw_name, tool_args, httpx_client_factory=None, **_options
    ):
        self.calls.append(raw_name)
        return {"success": True, "result": "[]"}


class Ledger:
    """The spend ledger, keyed like the real table on (event id, category)."""

    def __init__(self):
        self.lines = {}

    def __call__(self, session, user_context):
        return self

    async def record(self, entries):
        new = [e for e in entries if (e.event_id, e.category) not in self.lines]
        for entry in new:
            self.lines[(entry.event_id, entry.category)] = entry
        return len(new)


class Billing:
    """Billing as the platform asks it: a hold per platform call, quotes for display."""

    def __init__(self, allow=True):
        self.allow = allow
        self.authorizations, self.voids = [], []

    def currency(self):
        return "RUB"

    async def authorize(self, **request):
        self.authorizations.append(request)
        return SimpleNamespace(
            allowed=self.allow,
            code="ok" if self.allow else "no_credits",
            reason="" if self.allow else "no credits remaining",
            hold_id=f"hold-{len(self.authorizations)}" if self.allow else None,
            amount=Decimal("0.64") if self.allow else None,
            currency="RUB" if self.allow else None,
            expires_at=None,
        )

    async def void(self, *, hold_id):
        self.voids.append(hold_id)

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures, not the activity")

    async def quote(self, lines):
        raise AssertionError("every cost here is in the deployment currency")


def _install_gateway(monkeypatch, activity_fns, *, managed_by="platform", billing=None):
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry

    ctx, _ = activity_fns
    service = GatewayService(managed_by)
    ctx.get_mcp_server_instance_service = AsyncMock(return_value=service)
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "RUB")
    monkeypatch.setattr(
        tool_activities,
        "_offload_large_activity_output",
        AsyncMock(side_effect=lambda **k: k["content"]),
    )
    ledger = Ledger()
    monkeypatch.setattr(tool_activities, "CostEntryRepository", ledger)
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    billing = billing or Billing()
    ExtensionRegistry.register("tool_billing", lambda: billing)
    return service, ledger, billing


@pytest.fixture(autouse=True)
def _clear_billing():
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry

    yield
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


def _gateway_request(raw_name: str = "yandex_search") -> MCPToolRequest:
    return _request(
        tool_name=f"yandex__{raw_name}",
        tool_args={"query": "agentarea"},
        tools=[{"type": "mcp", "name": GATEWAY_ID}],
        mcp_route=McpToolRoute(
            instance_id=GATEWAY_ID, raw_name=raw_name, attachment_ref=GATEWAY_ID
        ),
    )


@pytest.mark.asyncio
async def test_a_platform_call_holds_then_writes_one_line_at_the_held_amount(
    monkeypatch, activity_fns
):
    from agentarea_tasks.domain.costs import tool_call_event_id

    _, execute_mcp_tool_activity = activity_fns
    service, ledger, billing = _install_gateway(monkeypatch, activity_fns)
    request = _gateway_request()

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, request)
    retry = ActivityEnvironment()
    retry.info = dataclasses.replace(retry.info, attempt=2)
    again = await retry.run(execute_mcp_tool_activity, request)

    assert (result.replayed, result.attempt) == (False, None)
    assert (again.replayed, again.attempt) == (True, 2)
    assert result.success is True
    assert (result.payer, result.cost, result.cost_metered) == (
        "platform",
        Decimal("0.64"),
        True,
    )
    assert service.calls == ["yandex_search", "yandex_search"]
    first = billing.authorizations[0]
    assert (first["connector"], first["tool"], first["vendor_cost"]) == (
        "ru.yandex/search-api",
        "yandex_search",
        Decimal("0.488"),
    )
    # The retry's hold is released: the first attempt's line carries the one captured.
    assert billing.voids == ["hold-2"]
    [line] = ledger.lines.values()
    assert line.event_id == tool_call_event_id(f"{request.task_id}:call_1")
    assert (str(line.task_id), line.agent_id, line.client_id) == (
        request.task_id,
        request.agent_id,
        None,
    )
    assert (line.subject_id, line.subject_name, line.payer.value) == (
        GATEWAY_ID,
        "yandex_search",
        "platform",
    )
    assert (line.vendor_cost, line.vendor_currency, line.amount, line.currency) == (
        Decimal("0.488"),
        "RUB",
        Decimal("0.64"),
        "RUB",
    )
    assert (line.quantity, line.unit, line.source.value) == (Decimal(1), "request", "rate")
    assert line.estimate is True
    assert line.evidence == {
        "connector": "ru.yandex/search-api",
        "tool_name": "yandex__yandex_search",
        "hold_id": "hold-1",
        "settle": "capture",
    }


@pytest.mark.asyncio
async def test_a_customer_key_call_is_metered_without_asking_billing(monkeypatch, activity_fns):
    _, execute_mcp_tool_activity = activity_fns
    _, ledger, billing = _install_gateway(monkeypatch, activity_fns, managed_by=None)

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, _gateway_request())

    assert (result.payer, result.cost) == ("workspace", Decimal("0.488"))
    assert billing.authorizations == []
    [line] = ledger.lines.values()
    assert (line.payer.value, line.amount) == ("workspace", Decimal("0.488"))


@pytest.mark.asyncio
async def test_no_balance_refuses_before_the_vendor_is_called(monkeypatch, activity_fns, audit):
    _, execute_mcp_tool_activity = activity_fns
    service, ledger, _ = _install_gateway(monkeypatch, activity_fns, billing=Billing(allow=False))

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, _gateway_request())

    assert result.success is False
    assert "no credits remaining" in (result.error or "")
    assert service.calls == [] and ledger.lines == {}
    [row] = audit.rows.values()
    assert row["action"] == "tool.call.denied"


@pytest.mark.asyncio
async def test_a_platform_tool_its_catalog_entry_does_not_price_is_refused(
    monkeypatch, activity_fns
):
    _, execute_mcp_tool_activity = activity_fns
    service, _, _ = _install_gateway(monkeypatch, activity_fns)

    result = await ActivityEnvironment().run(
        execute_mcp_tool_activity, _gateway_request(raw_name="undeclared")
    )

    assert result.success is False
    assert "declares no cost" in (result.error or "")
    assert service.calls == []


@pytest.mark.asyncio
async def test_a_free_call_costs_nothing(monkeypatch, activity_fns):
    _, execute_mcp_tool_activity = activity_fns
    _prepare_fake_code_tool(monkeypatch)
    request = _request(
        tool_name="example", tool_args={}, tools=[{"type": "code", "name": "agentarea/example"}]
    )

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, request)

    assert (result.payer, result.cost, result.cost_metered) == (None, 0, True)


@pytest.mark.asyncio
async def test_a_result_the_server_served_from_its_cache_is_marked_replayed(
    monkeypatch, activity_fns
):
    _, execute_mcp_tool_activity = activity_fns
    service, ledger, _ = _install_gateway(monkeypatch, activity_fns, managed_by=None)

    async def cached(instance_id, raw_name, tool_args, httpx_client_factory=None, **_options):
        return {"success": True, "result": "[]", "meta": {"agentarea/replayed": True}}

    service.execute_tool = cached

    result = await ActivityEnvironment().run(execute_mcp_tool_activity, _gateway_request())

    assert result.replayed is True
    assert len(ledger.lines) == 1
