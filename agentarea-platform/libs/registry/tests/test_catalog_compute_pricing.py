"""The expected hourly price of a connections catalog entry that runs on AgentArea."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_mcp.instance_reservation import InstanceReservation
from agentarea_registry.application import catalog_pricing
from agentarea_registry.application.catalog_pricing import ComputeEstimate, price_catalog_item

RESERVATION = InstanceReservation(vcpu=Decimal("0.1"), memory_gib=Decimal("0.125"))


class _Billing:
    def currency(self) -> str:
        return "RUB"

    async def price_llm_call(self, **_):
        return Decimal(0)

    async def price_compute_hour(self, *, vcpu, memory_gib):
        return vcpu * Decimal(1) + memory_gib * Decimal("0.12")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    async def reservation():
        return RESERVATION

    monkeypatch.setattr(catalog_pricing, "instance_reservation", reservation)
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()
    yield
    ExtensionRegistry.clear()
    get_customer_pricing.cache_clear()


def _item(hosting: str | None) -> SimpleNamespace:
    return SimpleNamespace(id="i1", hosting=hosting, spec={}, pricing="free")


async def test_a_hosted_entry_shows_its_reservation_and_no_price_without_billing():
    pricing = await price_catalog_item(_item("agentarea"))

    assert pricing is not None
    assert pricing.kind == "free"
    assert pricing.compute == ComputeEstimate(Decimal("0.1"), Decimal("0.125"), None, None)


async def test_with_billing_the_hour_is_priced_in_its_currency():
    ExtensionRegistry.register("customer_pricing", _Billing)

    pricing = await price_catalog_item(_item("agentarea"))

    assert pricing is not None
    assert pricing.compute == ComputeEstimate(
        Decimal("0.1"), Decimal("0.125"), Decimal("0.115"), "RUB"
    )


async def test_a_vendor_hosted_entry_reserves_nothing_of_ours():
    pricing = await price_catalog_item(_item("vendor"))

    assert pricing is not None
    assert pricing.compute is None
