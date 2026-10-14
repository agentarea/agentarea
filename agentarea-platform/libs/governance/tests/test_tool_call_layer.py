"""The one layer every tool call passes, from a run or from /mcp (wiki ADR-0038).

In order: the policy verdict (the runtime PDP); the cost before the call; for a call
on the platform's key, a hold placed by billing; the spend gate (caps over the
ledger, given what the call will cost); the call; and the meter, which hands the
caller's ledger one line per known cost: the connector's declared cost, and each
wallet payment the call made. A refused call never reaches the vendor, and a hold
whose call did not run is voided.
"""

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
)
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.tool_cost import CostSourceKind, Payer, parse_cost_model
from agentarea_governance.tool_calls import (
    GovernedToolCall,
    ToolCallOutcome,
    ToolConnection,
    Verdict,
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


class Billing:
    """Billing as the platform sees it: holds, captures, voids and quotes, in RUB."""

    def __init__(self, *, allowed=True, code="ok", amount="0.64", raises=False, quote_raises=False):
        self.allowed, self.code, self.amount = allowed, code, Decimal(amount)
        self.raises, self.quote_raises = raises, quote_raises
        self.authorizations, self.voids, self.quotes = [], [], []

    def currency(self):
        return "RUB"

    async def authorize(self, **request):
        self.authorizations.append(request)
        if self.raises:
            raise RuntimeError("billing unreachable")
        return SimpleNamespace(
            allowed=self.allowed,
            code=self.code,
            reason="no credits remaining" if not self.allowed else "",
            hold_id="hold-1" if self.allowed else None,
            amount=self.amount if self.allowed else None,
            currency="RUB" if self.allowed else None,
            expires_at=None,
        )

    async def capture(self, **request):
        raise AssertionError("the layer never captures; the settlement worker does")

    async def void(self, *, hold_id):
        self.voids.append(hold_id)

    async def quote(self, lines):
        self.quotes.extend(lines)
        if self.quote_raises:
            raise RuntimeError("billing unreachable")
        return [
            SimpleNamespace(
                amount=line.vendor_cost * (Decimal(95) if line.vendor_currency == "USD" else 1),
                code="ok",
            )
            for line in lines
        ]


class Vendor:
    def __init__(self, success=True, body=None, payments=(), meta=None):
        self.calls = 0
        self.success, self.body, self.payments, self.meta = success, body, payments, meta

    async def __call__(self):
        self.calls += 1
        return ToolCallOutcome(
            success=self.success,
            value="data",
            body=self.body,
            meta=self.meta,
            payments=self.payments,
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

    async def __call__(self, call, pending):
        self.calls.append((call, pending))
        return self.refusal


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "RUB")
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    yield
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


def _install(billing=None):
    billing = billing or Billing()
    ExtensionRegistry.register("tool_billing", lambda: billing)
    return billing


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
    assert (usage.amount, usage.currency, usage.estimate) == (Decimal("0.488"), "RUB", True)
    assert (usage.line_key, usage.agent_id, usage.task_id) == ("call-9", AGENT, "task-1")
    assert result.cost == Decimal("0.488")


async def test_a_customer_key_call_places_no_hold():
    billing = _install()

    await _run(_call(connection=_connection()))

    assert billing.authorizations == []


async def test_the_spend_gate_is_told_what_the_call_will_cost_before_it_runs():
    gate = SpendGate()
    cost = {
        "source": "rate",
        "rate": {"amount": "0.01", "currency": "RUB", "quantity": {"arg": "n", "default": 50}},
    }

    await _run(_call(connection=_connection(cost=cost)), gate=gate)

    [(_, pending)] = gate.calls
    assert pending == (Decimal("0.50"), "RUB")


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


async def test_a_platform_call_holds_what_billing_charges_and_its_line_carries_the_hold():
    billing = _install()
    gate, ledger = SpendGate(), Ledger()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), ledger=ledger, gate=gate)

    [request] = billing.authorizations
    assert request["workspace_id"] == "ws-1"
    assert (request["connector"], request["tool"]) == ("ru.yandex/search-api", "web_search")
    assert (request["vendor_cost"], request["vendor_currency"]) == (Decimal("0.488"), "RUB")
    assert request["idempotency_key"].startswith("hold:call-9:")
    [(_, pending)] = gate.calls
    assert pending == (Decimal("0.64"), "RUB")
    [usage] = ledger.lines
    assert (usage.payer, usage.vendor_cost, usage.amount, usage.currency, usage.estimate) == (
        Payer.PLATFORM,
        Decimal("0.488"),
        Decimal("0.64"),
        "RUB",
        True,
    )
    assert usage.evidence == {"hold_id": "hold-1", "settle": "capture"}
    assert result.verdict is Verdict.RAN and billing.voids == []


async def test_no_credits_refuses_a_platform_call_before_the_vendor():
    _install(Billing(allowed=False, code="no_credits"))
    vendor, ledger = Vendor(), Ledger()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), vendor, ledger=ledger)

    assert result.verdict is Verdict.DENIED
    assert "no_credits" in result.decision.reason
    assert vendor.calls == 0 and ledger.lines == []


async def test_billing_down_refuses_a_platform_call_and_lets_an_own_key_call_run(caplog):
    billing = _install(Billing(raises=True))
    vendor = Vendor()

    platform = await _run(_call(connection=_connection(Payer.PLATFORM)), vendor)
    own = await _run(_call(connection=_connection()), vendor)

    assert platform.verdict is Verdict.DENIED
    assert "billing" in platform.decision.reason
    assert own.verdict is Verdict.RAN and vendor.calls == 1
    assert len(billing.authorizations) == 1
    assert "billing unreachable" in caplog.text


async def test_a_cap_refusal_after_the_hold_voids_it():
    billing = _install()
    vendor = Vendor()

    result = await _run(
        _call(connection=_connection(Payer.PLATFORM)), vendor, gate=SpendGate("cap reached")
    )

    assert result.verdict is Verdict.DENIED
    assert billing.voids == ["hold-1"] and vendor.calls == 0


async def test_a_failed_platform_call_voids_its_hold_and_writes_no_line():
    billing, ledger = _install(), Ledger()

    await _run(_call(connection=_connection(Payer.PLATFORM)), Vendor(success=False), ledger=ledger)

    assert billing.voids == ["hold-1"] and ledger.lines == []


async def test_a_platform_call_that_raises_voids_its_hold():
    billing = _install()

    async def broken():
        raise RuntimeError("vendor exploded")

    with pytest.raises(RuntimeError, match="exploded"):
        await _run(_call(connection=_connection(Payer.PLATFORM)), broken)

    assert billing.voids == ["hold-1"]


async def test_a_retry_whose_line_is_already_written_voids_its_own_new_hold():
    billing, ledger = _install(), CountingLedger()

    await _run(_call(connection=_connection(Payer.PLATFORM)), ledger=ledger)
    again = await _run(_call(connection=_connection(Payer.PLATFORM)), ledger=ledger)

    assert again.replayed and len(ledger.lines) == 1
    assert billing.voids == ["hold-1"]


async def test_a_platform_tool_whose_cost_is_unknown_before_the_call_is_refused():
    billing = _install()
    vendor = Vendor()
    reported = {"source": "reported", "reported": {"path": "$.cost", "currency": "RUB"}}

    result = await _run(_call(connection=_connection(Payer.PLATFORM, cost=reported)), vendor)

    assert result.verdict is Verdict.DENIED
    assert "estimate" in result.decision.reason
    assert vendor.calls == 0 and billing.authorizations == []


async def test_without_billing_a_platform_call_is_governed_by_policy_and_caps_only():
    """OSS: a self-hoster's shared key has no balance, only PDP and caps."""
    gate, ledger = SpendGate(), Ledger()

    result = await _run(_call(connection=_connection(Payer.PLATFORM)), ledger=ledger, gate=gate)

    assert result.verdict is Verdict.RAN
    assert len(gate.calls) == 1
    [usage] = ledger.lines
    assert (usage.payer, usage.amount, usage.evidence) == (Payer.PLATFORM, Decimal("0.488"), {})


async def test_billing_that_failed_to_load_refuses_platform_calls(monkeypatch):
    monkeypatch.setattr(
        ExtensionRegistry,
        "get_failure",
        classmethod(lambda cls, name: "ImportError: x" if name == "tool_billing" else None),
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


REPORTED_USD = {"source": "reported", "reported": {"path": "$.cost", "currency": "USD"}}


async def test_a_reported_cost_in_another_currency_is_not_converted_without_billing():
    ledger = Ledger()

    result = await _run(
        _call(connection=_connection(cost=REPORTED_USD)),
        Vendor(body={"cost": "0.02", "tasks": []}),
        ledger=ledger,
    )

    [usage] = ledger.lines
    assert (usage.vendor_cost, usage.vendor_currency, usage.amount, usage.currency) == (
        Decimal("0.02"),
        "USD",
        Decimal("0.02"),
        "USD",
    )
    assert usage.estimate is False
    assert result.cost == Decimal(0)


async def test_billing_converts_a_foreign_currency_cost_on_the_customers_key_without_markup():
    billing, ledger = _install(), Ledger()

    await _run(
        _call(connection=_connection(cost=REPORTED_USD)),
        Vendor(body={"cost": "0.02"}),
        ledger=ledger,
    )

    [usage] = ledger.lines
    assert (usage.amount, usage.currency) == (Decimal("1.90"), "RUB")
    [line] = billing.quotes
    assert (line.payer, line.vendor_cost, line.vendor_currency) == (
        "workspace",
        Decimal("0.02"),
        "USD",
    )


async def test_a_conversion_billing_cannot_answer_is_left_for_settlement(caplog):
    _install(Billing(quote_raises=True))
    ledger = Ledger()

    await _run(
        _call(connection=_connection(cost=REPORTED_USD)),
        Vendor(body={"cost": "0.02"}),
        ledger=ledger,
    )

    [usage] = ledger.lines
    assert (usage.amount, usage.currency, usage.estimate) == (Decimal("0.02"), "USD", True)
    assert usage.evidence == {"settle": "convert", "vendor_exact": True}
    assert "could not be converted" in caplog.text


async def test_a_settled_cost_writes_its_estimate_and_what_to_settle_it_with():
    ledger = Ledger()
    cost = {
        "source": "settled",
        "estimate": {"amount": "0.10", "currency": "RUB"},
        "settled": {
            "fetch": {
                "url": "https://api.apify.com/v2/actor-runs/{run_id}",
                "params": {"run_id": "$.data.id"},
                "cost": "$.data.usageTotalUsd",
                "currency": "RUB",
            }
        },
    }

    await _run(
        _call(connection=_connection(cost=cost)), Vendor(body={"data": {"id": "r1"}}), ledger=ledger
    )

    [usage] = ledger.lines
    assert (usage.source, usage.amount, usage.estimate) == (
        CostSourceKind.SETTLED,
        Decimal("0.10"),
        True,
    )
    assert usage.evidence == {"settle": "vendor", "settle_params": {"run_id": "r1"}}


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
    billing, gate, vendor = _install(), SpendGate(), Vendor()

    result = await _run(
        _call(connection=_connection(Payer.PLATFORM), policy={"tools": {"denied": ["yandex__*"]}}),
        vendor,
        gate=gate,
    )

    assert result.verdict is Verdict.DENIED
    assert billing.authorizations == [] and gate.calls == [] and vendor.calls == 0


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
