"""A line that is not final is finalised by the line that supersedes it (ADR-0038 §2.7).

A held platform line is captured and replaced by what billing charged; a settled cost
is replaced by what the vendor finally says; a conversion billing could not make when
the line was written is made later. Nothing is final while what it waits on is not
there yet.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.tool_cost import CostSourceKind, MeteredCost, Payer
from agentarea_tasks.cost_settlement import settle
from agentarea_tasks.domain.costs import CostSource


class Billing:
    def __init__(self, quote_raises=False):
        self.captures, self.quote_raises = [], quote_raises

    def currency(self):
        return "EUR"

    async def authorize(self, **request):
        raise AssertionError("settlement places no hold")

    async def capture(self, **request):
        self.captures.append(request)
        return SimpleNamespace(amount=Decimal("0.66"), currency="EUR")

    async def void(self, *, hold_id):
        raise AssertionError("settlement voids nothing")

    async def quote(self, lines):
        if self.quote_raises:
            raise RuntimeError("billing unreachable")
        return [SimpleNamespace(amount=line.vendor_cost * 95, code="ok") for line in lines]


@pytest.fixture(autouse=True)
def eur(monkeypatch):
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    yield
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


def _install(billing=None):
    billing = billing or Billing()
    ExtensionRegistry.register("tool_billing", lambda: billing)
    return billing


def _line(**overrides):
    line = {
        "id": uuid4(),
        "event_id": uuid4(),
        "workspace_id": "ws-1",
        "created_by": "runner",
        "category": "service",
        "task_id": uuid4(),
        "agent_id": uuid4(),
        "client_id": None,
        "subject_type": "tool",
        "subject_id": "conn-1",
        "subject_name": "web_search",
        "call_ref": "call-9",
        "amount": Decimal("0.64"),
        "currency": "EUR",
        "source": "rate",
        "occurred_at": datetime(2026, 10, 14, 12, tzinfo=UTC),
        "provider_cost_usd": None,
        "payer": "platform",
        "quantity": Decimal(1),
        "unit": "request",
        "vendor_cost": Decimal("0.488"),
        "vendor_currency": "EUR",
        "evidence": {
            "connector": "example.com/search-api",
            "tool_name": "example__web_search",
            "hold_id": "hold-1",
            "settle": "capture",
        },
        "estimate": True,
        "supersedes_id": None,
    }
    return SimpleNamespace(**{**line, **overrides})


async def _no_vendor(line):
    raise AssertionError("no vendor settlement expected")


async def test_a_held_line_is_captured_and_superseded_by_what_billing_charged():
    billing = _install()
    line = _line()

    successor = await settle(line, _no_vendor)

    [capture] = billing.captures
    assert capture["hold_id"] == "hold-1"
    assert (capture["vendor_cost"], capture["vendor_currency"]) == (Decimal("0.488"), "EUR")
    assert capture["idempotency_key"] == f"tool:{line.event_id}"
    assert (successor.amount, successor.currency, successor.estimate) == (
        Decimal("0.66"),
        "EUR",
        False,
    )
    assert successor.supersedes_id == line.id
    assert successor.occurred_at == line.occurred_at
    assert successor.evidence == {
        "connector": "example.com/search-api",
        "tool_name": "example__web_search",
        "hold_id": "hold-1",
    }
    # Settling the same line again is the same successor, which the ledger stores once.
    assert (await settle(line, _no_vendor)).event_id == successor.event_id


async def test_a_held_line_without_billing_installed_is_an_error():
    with pytest.raises(RuntimeError, match="no billing"):
        await settle(_line(), _no_vendor)


APIFY_LINE = {
    "payer": "workspace",
    "source": "settled",
    "amount": Decimal("0.10"),
    "currency": "USD",
    "vendor_cost": Decimal("0.10"),
    "vendor_currency": "USD",
    "evidence": {
        "connector": "com.apify/mcp",
        "settle": "vendor",
        "settle_params": {"run_id": "r"},
    },
}


async def test_a_settled_cost_waits_until_the_vendor_is_done():
    async def running(line):
        return None

    assert await settle(_line(**APIFY_LINE), running) is None


async def _done(line):
    assert line.evidence["settle_params"] == {"run_id": "r"}
    return MeteredCost(Decimal(1), "call", Decimal("0.0123"), "USD", CostSourceKind.SETTLED)


async def test_a_settled_figure_is_read_again_before_it_counts_as_final():
    """A vendor may still add to a run's cost for seconds after reporting it done."""
    first = await settle(_line(**APIFY_LINE), _done)

    assert (first.vendor_cost, first.amount, first.estimate) == (
        Decimal("0.0123"),
        Decimal("0.10"),
        True,
    )
    assert first.evidence["settle"] == "vendor"
    assert first.evidence["settle_params"] == {"run_id": "r"}


async def test_a_settled_cost_supersedes_the_estimate_in_the_deployment_currency():
    _install()
    read_once = {**APIFY_LINE, "vendor_cost": Decimal("0.0123"), "supersedes_id": uuid4()}

    successor = await settle(_line(**read_once), _done)

    assert (successor.vendor_cost, successor.vendor_currency) == (Decimal("0.0123"), "USD")
    assert (successor.amount, successor.currency, successor.estimate) == (
        Decimal("1.1685"),
        "EUR",
        False,
    )
    assert successor.source is CostSource.SETTLED
    assert successor.evidence == {"connector": "com.apify/mcp"}


async def test_a_settled_platform_cost_is_then_captured():
    async def done(line):
        return MeteredCost(Decimal(1), "call", Decimal("0.3"), "EUR", CostSourceKind.SETTLED)

    line = _line(
        source="settled",
        vendor_cost=Decimal("0.3"),
        supersedes_id=uuid4(),
        evidence={**_line().evidence, "settle": "vendor"},
    )

    successor = await settle(line, done)

    assert (successor.vendor_cost, successor.amount, successor.estimate) == (
        Decimal("0.3"),
        Decimal("0.64"),
        True,
    )
    assert successor.evidence["settle"] == "capture"
    assert successor.payer is Payer.PLATFORM


async def test_a_conversion_is_made_once_billing_answers():
    line = _line(
        payer="workspace",
        source="reported",
        amount=Decimal("0.02"),
        currency="USD",
        vendor_cost=Decimal("0.02"),
        vendor_currency="USD",
        evidence={"connector": "x", "settle": "convert", "vendor_exact": True},
    )
    _install(Billing(quote_raises=True))

    assert await settle(line, _no_vendor) is None

    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    _install()
    successor = await settle(line, _no_vendor)

    assert (successor.amount, successor.currency, successor.estimate) == (
        Decimal("1.90"),
        "EUR",
        False,
    )
    assert successor.evidence == {"connector": "x"}


async def test_a_held_model_line_is_captured_as_a_model_call():
    billing = _install()
    line = _line(
        subject_type="model_instance",
        subject_id="model-1",
        subject_name="kimi-k3",
        vendor_cost=Decimal("0.02"),
        vendor_currency="USD",
        evidence={"hold_id": "hold-9", "settle": "capture", "prompt_tokens": 10},
    )

    successor = await settle(line, _no_vendor)

    [capture] = billing.captures
    assert (capture["kind"], capture["connector"], capture["tool"]) == ("model", "llm", "model-1")
    assert (capture["vendor_cost"], capture["vendor_currency"]) == (Decimal("0.02"), "USD")
    assert (successor.amount, successor.estimate) == (Decimal("0.66"), False)
    assert successor.evidence == {"hold_id": "hold-9", "prompt_tokens": 10}
