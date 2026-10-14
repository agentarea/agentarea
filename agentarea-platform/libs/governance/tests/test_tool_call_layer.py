"""The one layer every tool call passes, from a run or from /mcp (wiki ADR-0038).

In order: the policy verdict (the runtime PDP); the spend gate (caps over the
ledger); for a call on the platform's key, the balance gate; the call; and the
meter, which hands the caller's ledger one line per known cost: the connector's
declared cost, and each wallet payment the call made. A refused call never reaches
the vendor.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
)
from agentarea_common.extensions import customer_pricing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.tool_cost import CostSourceKind, Payer, parse_cost_model
from agentarea_governance.domain.enums import InterceptorAction, InterceptorCategory, Phase
from agentarea_governance.domain.models import InterceptorResult
from agentarea_governance.tool_calls import (
    GovernedToolCall,
    ToolCallOutcome,
    ToolConnection,
    Verdict,
    entitlement_guard,
    run_tool_call,
)

AGENT = UUID(int=7)
RATE = {"source": "rate", "unit": "request", "rate": {"amount": "0.488", "currency": "RUB"}}


class Ledger:
    def __init__(self, raises=False):
        self.lines = []
        self.raises = raises

    async def __call__(self, usages):
        if self.raises:
            raise RuntimeError("db down")
        self.lines.extend(usages)


class Guard:
    name = "entitlement_guard"
    category = InterceptorCategory.GATE

    def __init__(self, action=InterceptorAction.ALLOW, reason="ok"):
        self.action, self.reason = action, reason
        self.contexts = []

    async def execute(self, context):
        self.contexts.append(context)
        return InterceptorResult(action=self.action, interceptor_name=self.name, reason=self.reason)


class Vendor:
    def __init__(self, success=True, body=None, payments=()):
        self.calls = 0
        self.success, self.body, self.payments = success, body, payments

    async def __call__(self):
        self.calls += 1
        return ToolCallOutcome(
            success=self.success, value="data", body=self.body, payments=self.payments
        )


class Audit:
    def __init__(self):
        self.decisions = []

    async def __call__(self, decision):
        self.decisions.append(decision)


class SpendGate:
    def __init__(self, refusal=None):
        self.refusal = refusal
        self.calls = []

    async def __call__(self, call):
        self.calls.append(call)
        return self.refusal


class Rub(customer_pricing.ProviderCostPricing):
    def currency(self) -> str:
        return "RUB"

    async def price_vendor_cost(self, *, payer, connector, tool, vendor_cost, currency):
        fx = Decimal(95) if currency == "USD" else Decimal(1)
        return vendor_cost * fx * (Decimal("1.5") if payer == "platform" else Decimal(1))


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(customer_pricing, "get_customer_pricing", lambda: Rub())
    ExtensionRegistry.clear()
    entitlement_guard.cache_clear()
    yield
    ExtensionRegistry.clear()
    entitlement_guard.cache_clear()


def _install(guard=None):
    guard = guard or Guard()
    ExtensionRegistry.register("entitlement_guard", lambda: guard)
    return guard


def _connection(payer=Payer.WORKSPACE, cost=RATE):
    return ToolConnection(
        connection_id="conn-1",
        connector="ru.yandex/search-api",
        tool="web_search",
        payer=payer,
        cost_model=parse_cost_model(cost),
    )


def _call(*, connection=None, policy=None, approved=False, task_id="task-1", client_id=None):
    return GovernedToolCall(
        authorization=ToolAuthorizationRequest(
            tool_name="yandex__web_search",
            tool_args={"query": "agentarea"},
            user_id="runner",
            workspace_id="ws-1",
            effective_policy=policy,
        ),
        call_id="call-9",
        agent_id=AGENT,
        task_id=task_id,
        client_id=client_id,
        connection=connection,
        approval_granted=approved,
    )


async def _run(call, vendor=None, *, ledger=None, audit=None, gate=None):
    return await run_tool_call(
        call,
        vendor or Vendor(),
        audit=audit or Audit(),
        ledger=ledger if ledger is not None else Ledger(),
        spend_gate=gate or SpendGate(),
    )


async def test_a_call_on_the_customers_key_writes_a_line_at_its_declared_rate():
    ledger = Ledger()

    result = await _run(_call(connection=_connection()), ledger=ledger)

    assert result.verdict is Verdict.RAN and result.metered
    [usage] = ledger.lines
    assert usage == result.usages[0]
    assert (usage.connection_id, usage.connector, usage.tool, usage.tool_name) == (
        "conn-1",
        "ru.yandex/search-api",
        "web_search",
        "yandex__web_search",
    )
    assert (usage.payer, usage.source, usage.quantity, usage.unit) == (
        Payer.WORKSPACE,
        CostSourceKind.RATE,
        Decimal(1),
        "request",
    )
    assert (usage.vendor_cost, usage.vendor_currency) == (Decimal("0.488"), "RUB")
    assert (usage.amount, usage.currency) == (Decimal("0.488"), "RUB")
    assert (usage.line_key, usage.agent_id, usage.task_id) == ("call-9", AGENT, "task-1")
    assert result.cost == Decimal("0.488")


async def test_a_customer_key_call_asks_no_balance_gate():
    guard = _install()

    await _run(_call(connection=_connection()))

    assert guard.contexts == []


async def test_the_spend_gate_refuses_before_the_vendor_is_called():
    vendor, audit, ledger = Vendor(), Audit(), Ledger()

    result = await _run(
        _call(connection=_connection()),
        vendor,
        audit=audit,
        ledger=ledger,
        gate=SpendGate("agent spend cap of 1 RUB reached"),
    )

    assert result.verdict is Verdict.DENIED
    assert "spend cap" in result.decision.reason
    assert vendor.calls == 0 and ledger.lines == []
    assert [d.action for d in audit.decisions] == [ToolAuthorizationAction.DENY]


async def test_a_platform_call_is_gated_on_the_balance_by_vendor_cost_and_connector():
    guard = _install()
    ledger = Ledger()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), ledger=ledger)

    [context] = guard.contexts
    assert context.phase is Phase.PRE_TOOL_CALL
    assert (context.workspace_id, context.user_id, context.agent_id) == ("ws-1", "runner", AGENT)
    assert context.execution_state["paid_call"] == {
        "payer": "platform",
        "metric_type": "tool.vendor_cost.RUB",
        "resource_ref": "ru.yandex/search-api#web_search",
    }
    [usage] = ledger.lines
    assert (usage.payer, usage.vendor_cost, usage.amount) == (
        Payer.PLATFORM,
        Decimal("0.488"),
        Decimal("0.7320"),
    )
    assert result.verdict is Verdict.RAN


async def test_no_balance_refuses_a_platform_call_before_the_vendor():
    _install(Guard(InterceptorAction.DENY, "no credits remaining"))
    vendor, ledger = Vendor(), Ledger()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), vendor, ledger=ledger)

    assert result.verdict is Verdict.DENIED
    assert "no credits remaining" in result.decision.reason
    assert vendor.calls == 0 and ledger.lines == []


async def test_without_a_balance_gate_a_platform_call_is_governed_by_policy_and_caps_only():
    """OSS: a self-hoster's shared key has no balance, only PDP and caps."""
    gate, ledger = SpendGate(), Ledger()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), ledger=ledger, gate=gate)

    assert result.verdict is Verdict.RAN
    assert len(gate.calls) == 1
    assert [u.payer for u in ledger.lines] == [Payer.PLATFORM]


async def test_a_balance_gate_that_failed_to_load_refuses_platform_calls(monkeypatch):
    monkeypatch.setattr(
        ExtensionRegistry,
        "get_failure",
        classmethod(lambda cls, name: "ImportError: x" if name == "entitlement_guard" else None),
    )
    vendor = Vendor()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), vendor)

    assert result.verdict is Verdict.DENIED
    assert "failed to load" in result.decision.reason
    assert vendor.calls == 0


async def test_a_platform_tool_without_a_cost_model_is_refused():
    vendor = Vendor()

    result = await _run(_call(connection=_connection(Payer.PLATFORM, cost=None)), vendor)

    assert result.verdict is Verdict.DENIED
    assert "cost" in result.decision.reason
    assert vendor.calls == 0


async def test_a_reported_cost_is_read_from_the_response():
    ledger = Ledger()
    cost = {"source": "reported", "reported": {"path": "$.cost", "currency": "USD"}}

    await _run(
        _call(connection=_connection(cost=cost)),
        Vendor(body={"cost": "0.02", "tasks": []}),
        ledger=ledger,
    )

    [usage] = ledger.lines
    assert (usage.vendor_cost, usage.vendor_currency, usage.amount, usage.currency) == (
        Decimal("0.02"),
        "USD",
        Decimal("1.90"),
        "RUB",
    )


async def test_a_wallet_payment_is_a_per_call_line_of_the_same_layer():
    ledger = Ledger()
    payment = {
        "success": True,
        "protocol": "x402",
        "amount_usd": "0.01",
        "idempotency_key": "pay-1",
        "recipient": "0xabc",
        "tx_hash": "0xdef",
    }

    result = await _run(_call(), Vendor(payments=(payment,)), ledger=ledger)

    [usage] = ledger.lines
    assert (usage.payer, usage.source, usage.vendor_cost, usage.vendor_currency) == (
        Payer.PER_CALL,
        CostSourceKind.REPORTED,
        Decimal("0.01"),
        "USD",
    )
    assert usage.line_key == "call-9:payment:pay-1"
    assert usage.evidence == {"protocol": "x402", "recipient": "0xabc", "tx_hash": "0xdef"}
    assert result.cost == Decimal(0)


async def test_a_payment_that_did_not_settle_is_not_a_line():
    ledger = Ledger()

    await _run(_call(), Vendor(payments=({"success": False, "amount_usd": "1"},)), ledger=ledger)

    assert ledger.lines == []


async def test_a_call_from_a_registered_client_names_it_and_no_task():
    ledger = Ledger()

    await _run(_call(connection=_connection(), task_id=None, client_id="client-1"), ledger=ledger)

    [usage] = ledger.lines
    assert (usage.task_id, usage.client_id) == (None, "client-1")


async def test_policy_denies_before_any_gate():
    guard, gate, vendor = _install(), SpendGate(), Vendor()

    result = await _run(
        _call(connection=_connection(Payer.PLATFORM), policy={"tools": {"denied": ["yandex__*"]}}),
        vendor,
        gate=gate,
    )

    assert result.verdict is Verdict.DENIED
    assert guard.contexts == [] and gate.calls == [] and vendor.calls == 0


async def test_a_held_call_waits_for_its_approval_and_then_runs():
    policy = {"approval": {"escalation_rules": ["yandex__*"]}}
    vendor, ledger = Vendor(), Ledger()

    held = await _run(_call(connection=_connection(), policy=policy), vendor, ledger=ledger)
    ran = await _run(
        _call(connection=_connection(), policy=policy, approved=True), vendor, ledger=ledger
    )

    assert held.verdict is Verdict.HELD
    assert ran.verdict is Verdict.RAN
    assert vendor.calls == 1 and len(ledger.lines) == 1


async def test_a_free_or_unconnected_call_writes_nothing():
    ledger = Ledger()

    await _run(_call(connection=_connection(cost={"source": "free"})), ledger=ledger)
    await _run(_call(), ledger=ledger)

    assert ledger.lines == []


async def test_a_failed_call_records_no_declared_cost():
    ledger = Ledger()

    result = await _run(_call(connection=_connection()), Vendor(success=False), ledger=ledger)

    assert result.verdict is Verdict.RAN and ledger.lines == []


async def test_a_cost_the_response_does_not_carry_is_logged_not_invented(caplog):
    ledger = Ledger()
    cost = {"source": "reported", "reported": {"path": "$.cost", "currency": "USD"}}

    await _run(_call(connection=_connection(cost=cost)), Vendor(body={}), ledger=ledger)

    assert ledger.lines == []
    assert "could not be metered" in caplog.text


async def test_a_cost_in_a_currency_the_pricing_cannot_convert_keeps_the_vendor_currency(
    monkeypatch,
):
    monkeypatch.setattr(
        customer_pricing, "get_customer_pricing", lambda: customer_pricing.ProviderCostPricing()
    )
    ledger = Ledger()

    await _run(_call(connection=_connection()), ledger=ledger)

    [usage] = ledger.lines
    assert (usage.amount, usage.currency) == (Decimal("0.488"), "RUB")


async def test_a_failed_ledger_write_is_logged_and_the_result_still_returned(caplog):
    result = await _run(_call(connection=_connection()), ledger=Ledger(raises=True))

    assert result.verdict is Verdict.RAN
    assert result.outcome.value == "data"
    assert not result.metered
    assert "were not recorded" in caplog.text


class CountingLedger(Ledger):
    """Stores each line once by key and says how many it inserted, as the table does."""

    def __init__(self):
        super().__init__()
        self.keys = set()

    async def __call__(self, usages):
        new = [u for u in usages if u.line_key not in self.keys]
        self.keys.update(u.line_key for u in new)
        self.lines.extend(new)
        return len(new)


async def test_a_retried_call_writes_no_second_line_and_says_it_was_replayed():
    ledger = CountingLedger()

    first = await _run(_call(connection=_connection()), ledger=ledger)
    again = await _run(_call(connection=_connection()), ledger=ledger)

    assert len(ledger.lines) == 1
    assert (first.replayed, again.replayed) == (False, True)


async def test_a_result_the_vendor_served_from_its_cache_is_replayed():
    class Cached(Vendor):
        async def __call__(self):
            self.calls += 1
            return ToolCallOutcome(success=True, value="data", replayed=True)

    result = await _run(_call(), Cached())

    assert result.replayed is True
