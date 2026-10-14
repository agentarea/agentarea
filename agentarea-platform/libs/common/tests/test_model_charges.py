"""A model call's spend line, as billing says it (wiki ADR-0038 rev 2).

On the platform's credentials billing holds the estimated call and prices the actual
vendor cost right after it; when it cannot, the line keeps the hold to be captured,
never the vendor cost as a price. On the customer's own credentials the vendor cost
is the amount, converted by billing when the deployment is not in USD.
"""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agentarea_common import model_charges
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.model_charges import (
    ModelCallRefusedError,
    charge_model_call,
    hold_model_call,
    release_model_hold,
)


class Billing:
    def __init__(self, *, allowed=True, code="ok", quote_fails=False, slow=False):
        self.allowed, self.code, self.quote_fails, self.slow = allowed, code, quote_fails, slow
        self.authorizations, self.quotes, self.voids = [], [], []

    def currency(self):
        return "RUB"

    async def authorize(self, **request):
        self.authorizations.append(request)
        if self.slow:
            await asyncio.sleep(10)
        return SimpleNamespace(
            allowed=self.allowed,
            code=self.code,
            reason="no credits remaining" if not self.allowed else "",
            hold_id="hold-1" if self.allowed else None,
            amount=Decimal("19.00") if self.allowed else None,
            currency="RUB",
            expires_at=None,
        )

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures")

    async def void(self, *, hold_id):
        self.voids.append(hold_id)

    async def quote(self, lines):
        self.quotes.extend(lines)
        if self.quote_fails:
            raise RuntimeError("billing unreachable")
        factor = Decimal(95) * (Decimal("1.5") if lines[0].payer == "platform" else 1)
        return [SimpleNamespace(amount=line.vendor_cost * factor, code="ok") for line in lines]


@pytest.fixture(autouse=True)
def rub(monkeypatch):
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "RUB")
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    yield
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


def _install(billing):
    ExtensionRegistry.register("tool_billing", lambda: billing)
    return billing


async def _hold(**overrides):
    return await hold_model_call(
        **{
            "workspace_id": "ws-1",
            "model_instance_id": "model-1",
            "platform_funded": True,
            "vendor_cost_estimate": Decimal("0.20"),
            "idempotency_key": "llm:task:1",
            **overrides,
        }
    )


async def test_a_platform_call_is_held_by_its_estimated_vendor_cost_as_a_model():
    billing = _install(Billing())

    hold = await _hold()

    [request] = billing.authorizations
    assert (request["kind"], request["connector"], request["tool"]) == ("model", "llm", "model-1")
    assert (request["vendor_cost"], request["vendor_currency"]) == (Decimal("0.20"), "USD")
    assert hold.hold_id == "hold-1"


async def test_a_call_on_the_customers_key_or_without_billing_holds_nothing():
    billing = _install(Billing())

    assert await _hold(platform_funded=False) is None
    assert billing.authorizations == []
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    assert await _hold() is None


async def test_a_refused_or_unanswered_hold_refuses_the_call(monkeypatch):
    _install(Billing(allowed=False, code="no_credits"))
    with pytest.raises(ModelCallRefusedError) as refused:
        await _hold()
    assert refused.value.code == "no_credits"

    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    _install(Billing(slow=True))
    monkeypatch.setattr(tool_billing, "BILLING_TIMEOUT", 0.01)
    with pytest.raises(ModelCallRefusedError) as unanswered:
        await _hold()
    assert unanswered.value.code == "billing_unavailable"


async def test_the_line_of_a_held_call_is_billings_price_of_the_actual_cost():
    billing = _install(Billing())
    hold = await _hold()

    charge = await charge_model_call(
        model_instance_id="model-1", platform_funded=True, vendor_cost=Decimal("0.01"), hold=hold
    )

    [line] = billing.quotes
    assert (line.payer, line.kind, line.tool) == ("platform", "model", "model-1")
    assert (charge.amount, charge.currency) == (Decimal("1.425"), "RUB")
    assert (charge.estimate, charge.settle, charge.hold_id) == (True, "capture", "hold-1")
    assert (charge.vendor_cost, charge.vendor_currency) == (Decimal("0.01"), "USD")


async def test_billing_unable_to_price_leaves_the_held_amount_to_be_captured(caplog):
    _install(Billing(quote_fails=True))
    hold = await _hold()

    charge = await charge_model_call(
        model_instance_id="model-1", platform_funded=True, vendor_cost=Decimal("0.01"), hold=hold
    )

    assert (charge.amount, charge.currency, charge.settle) == (Decimal("19.00"), "RUB", "capture")
    assert "keeps its hold" in caplog.text


async def test_a_customer_key_call_is_its_vendor_cost_converted_without_markup():
    billing = _install(Billing())

    charge = await charge_model_call(
        model_instance_id="model-1", platform_funded=False, vendor_cost=Decimal("0.01"), hold=None
    )

    assert billing.quotes[0].payer == "workspace"
    assert (charge.amount, charge.currency, charge.settle) == (Decimal("0.95"), "RUB", None)


async def test_without_billing_a_call_is_its_vendor_cost_in_usd():
    charge = await charge_model_call(
        model_instance_id="model-1", platform_funded=True, vendor_cost=Decimal("0.01"), hold=None
    )

    assert (charge.amount, charge.currency, charge.estimate) == (Decimal("0.01"), "USD", False)


async def test_a_hold_whose_call_failed_is_voided():
    billing = _install(Billing())

    await release_model_hold(await _hold(), "the call failed")

    assert billing.voids == ["hold-1"]
    assert model_charges.SETTLE_CAPTURE == "capture"
