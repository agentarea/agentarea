"""What a connections catalog entry costs through AgentArea, as the browse API shows it.

The platform knows the vendor's cost only. With billing installed, the price on the
platform's key is billing's own answer, asked once per page; billing down, the vendor
cost is shown and said to be without our price.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.tool_cost import Payer
from agentarea_registry.application.catalog_facets import derive_facets
from agentarea_registry.application.catalog_pricing import (
    ToolPrice,
    price_catalog_item,
    price_catalog_items,
)


@pytest.fixture(autouse=True)
def no_billing(monkeypatch):
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "RUB")
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    yield
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


class Billing:
    def __init__(self, raises=False):
        self.raises = raises
        self.calls = []

    def currency(self):
        return "RUB"

    async def authorize(self, **request):
        raise AssertionError("browsing holds nothing")

    async def capture(self, **request):
        raise AssertionError("browsing charges nothing")

    async def void(self, *, hold_id):
        raise AssertionError("browsing holds nothing")

    async def quote(self, lines):
        self.calls.append(list(lines))
        if self.raises:
            raise RuntimeError("billing unreachable")
        return [
            SimpleNamespace(
                amount=None if line.tool == "unsold" else line.vendor_cost * Decimal("1.3"),
                code="tool_unpriced" if line.tool == "unsold" else "ok",
            )
            for line in lines
        ]


def _rate(amount: str, unit: str = "request") -> dict:
    return {"source": "rate", "unit": unit, "rate": {"amount": amount, "currency": "RUB"}}


def _item(metadata: dict, protocol: str = "api") -> SimpleNamespace:
    spec = {"raw_spec": {"name": "ru.yandex/search-api", "metadata": metadata}}
    return SimpleNamespace(
        id="i1",
        name="Yandex Search API",
        external_id="ru.yandex/search-api/openapi",
        protocol=protocol,
        spec=spec,
        pricing=derive_facets("mcp_servers", "x", spec, []).pricing,
    )


async def test_a_paid_entry_is_priced_per_tool_and_from_its_cheapest():
    pricing = await price_catalog_item(
        _item(
            {
                "agentarea:payers": ["workspace", "platform"],
                "agentarea:cost": {
                    "tools": {
                        "web_search": _rate("0.488"),
                        "wordstat_top": _rate("0.02"),
                        "later": {"source": "settled"},
                    }
                },
            }
        )
    )

    assert pricing is not None
    assert pricing.kind == "paid"
    assert pricing.payers == (Payer.WORKSPACE, Payer.PLATFORM)
    # Without an installed billing, what is shown is the vendor's cost.
    assert pricing.prices == (
        ToolPrice("web_search", Decimal("0.488"), "RUB", "request", "vendor_cost"),
        ToolPrice("wordstat_top", Decimal("0.02"), "RUB", "request", "vendor_cost"),
    )
    assert pricing.price_from == pricing.prices[1]


async def test_an_own_key_entry_names_no_price_of_ours():
    pricing = await price_catalog_item(_item({"agentarea:cost": {"default": _rate("1")}}))

    assert pricing is not None
    assert (pricing.kind, pricing.payers, pricing.prices) == ("own_key", (Payer.WORKSPACE,), ())


async def test_entries_without_a_pricing_dimension_have_none():
    assert await price_catalog_item(SimpleNamespace(pricing=None)) is None


def _paid(*tools):
    return _item(
        {
            "agentarea:payers": ["platform"],
            "agentarea:cost": {"tools": {tool: _rate("0.5") for tool in tools}},
        }
    )


async def test_with_billing_a_page_is_priced_by_billing_in_one_quote():
    billing = Billing()
    ExtensionRegistry.register("tool_billing", lambda: billing)

    first, second = await price_catalog_items([_paid("web_search", "unsold"), _paid("wordstat")])

    assert len(billing.calls) == 1
    assert [(line.payer, line.tool) for line in billing.calls[0]] == [
        ("platform", "web_search"),
        ("platform", "unsold"),
        ("platform", "wordstat"),
    ]
    # A tool billing does not price is not for sale on the platform's key.
    assert first.prices == (ToolPrice("web_search", Decimal("0.65"), "RUB", "request", "price"),)
    assert second.prices == (ToolPrice("wordstat", Decimal("0.65"), "RUB", "request", "price"),)


async def test_billing_down_shows_the_vendor_cost_as_without_our_price(caplog):
    ExtensionRegistry.register("tool_billing", lambda: Billing(raises=True))

    pricing = await price_catalog_item(_paid("web_search"))

    assert pricing.prices == (
        ToolPrice("web_search", Decimal("0.5"), "RUB", "request", "vendor_cost", unavailable=True),
    )
    assert "billing unreachable" in caplog.text
