"""What a connections catalog entry costs through AgentArea, as the browse API shows it."""

from decimal import Decimal
from types import SimpleNamespace

from agentarea_common.tool_cost import Payer
from agentarea_registry.application.catalog_facets import derive_facets
from agentarea_registry.application.catalog_pricing import ToolPrice, price_catalog_item


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
    # Without an installed billing, the platform key's price is the vendor's rate.
    assert pricing.prices == (
        ToolPrice("web_search", Decimal("0.488"), "RUB", "request"),
        ToolPrice("wordstat_top", Decimal("0.02"), "RUB", "request"),
    )
    assert pricing.price_from == ToolPrice("wordstat_top", Decimal("0.02"), "RUB", "request")


async def test_an_own_key_entry_names_no_price_of_ours():
    pricing = await price_catalog_item(_item({"agentarea:cost": {"default": _rate("1")}}))

    assert pricing is not None
    assert (pricing.kind, pricing.payers, pricing.prices) == ("own_key", (Payer.WORKSPACE,), ())


async def test_entries_without_a_pricing_dimension_have_none():
    assert await price_catalog_item(SimpleNamespace(pricing=None)) is None
