"""What using a connections catalog entry costs through AgentArea (wiki ADR-0038).

Whether an entry is paid is a browse facet, derived at sync time from what the
entry declares (``catalog_facets``). What a call costs the workspace is not: the
platform knows only the vendor's declared cost. With billing installed, the price on
the platform's key is billing's answer, asked live in one quote for every entry of a
page; billing down, the vendor cost is shown, marked as without our price. Without
billing the vendor cost is what there is to show.

An entry that runs on AgentArea also holds compute while its instance runs. That is
billed per hour of what the instance reserved, separately from any call, so it is a
separate estimate: the reservation as the MCP manager reports it, priced by billing
when one is installed and left unpriced otherwise.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Literal

from agentarea_common.extensions.customer_pricing import price_compute_hour
from agentarea_common.extensions.tool_billing import QuoteLine, get_tool_billing
from agentarea_common.tool_cost import (
    CostSourceKind,
    Payer,
    ToolCostError,
    connector_payers,
    parse_cost_model,
)
from agentarea_mcp.domain.metering import META_COST, META_PAYERS
from agentarea_mcp.instance_reservation import instance_reservation

from .catalog_facets import CatalogPricing, catalog_metadata

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolPrice:
    """What one unit of a tool's calls costs; ``tool`` None is the connector's default.

    ``basis`` "price" is billing's price on the platform's key, markup included;
    "vendor_cost" is the vendor's own cost. ``unavailable`` says billing was asked for
    its price and could not answer, so the vendor cost stands in, said to be one.
    """

    tool: str | None
    amount: Decimal
    currency: str
    unit: str
    basis: Literal["price", "vendor_cost"] = "vendor_cost"
    unavailable: bool = False


@dataclass(frozen=True)
class ComputeEstimate:
    """What a hosted entry's running instance reserves, and what an hour of it costs."""

    vcpu: Decimal
    memory_gib: Decimal
    # None when nothing prices compute (no billing installed): the reservation alone.
    hourly: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class CatalogItemPricing:
    kind: CatalogPricing
    payers: tuple[Payer, ...]
    # Per tool of a paid entry that declares rates; empty otherwise.
    prices: tuple[ToolPrice, ...]
    # Entries that run on AgentArea only; None where the reservation is unknown.
    compute: ComputeEstimate | None = None

    @property
    def price_from(self) -> ToolPrice | None:
        return min(self.prices, key=lambda price: price.amount, default=None)


def _connector(item: Any) -> str:
    """The connector id billing prices the entry's calls by, as metering names it."""
    if item.protocol == "api":
        return str(item.external_id)
    raw = (item.spec or {}).get("raw_spec") or {}
    return str(raw.get("name") or item.name)


def _vendor_costs(item: Any, metadata: dict[str, Any]) -> list[ToolPrice]:
    cost = metadata.get(META_COST) or {}
    declarations: list[tuple[str | None, Any]] = [
        (None, cost.get("default")),
        *((tool, declaration) for tool, declaration in (cost.get("tools") or {}).items()),
    ]
    prices: list[ToolPrice] = []
    for tool, declaration in declarations:
        if declaration is None:
            continue
        try:
            model = parse_cost_model(declaration)
        except ToolCostError:
            logger.warning(
                "Catalog entry %s declares a malformed cost for %s",
                _connector(item),
                tool,
                exc_info=True,
            )
            continue
        if model.source is not CostSourceKind.RATE or model.rate_amount is None:
            continue
        prices.append(ToolPrice(tool, model.rate_amount, model.currency or "", model.unit))
    return prices


async def _billing_prices(
    connectors: Sequence[str], costs: Sequence[ToolPrice]
) -> list[ToolPrice | None]:
    """Each vendor cost as billing prices it on the platform's key, in one quote.

    None for a tool billing does not price: it is not for sale on our key.
    """
    billing = get_tool_billing()
    if billing is None or not costs:
        return list(costs)
    lines = [
        QuoteLine(
            payer=Payer.PLATFORM.value,
            connector=connector,
            tool=cost.tool or "*",
            vendor_cost=cost.amount,
            vendor_currency=cost.currency,
        )
        for connector, cost in zip(connectors, costs, strict=True)
    ]
    try:
        quotes = list(await billing.quote(lines))
    except Exception:
        logger.error("Billing could not quote %d catalog prices", len(lines), exc_info=True)
        return [replace(cost, unavailable=True) for cost in costs]
    return [
        replace(cost, amount=quote.amount, currency=billing.currency(), basis="price")
        if quote.amount is not None
        else None
        for cost, quote in zip(costs, quotes, strict=True)
    ]


async def _compute_estimate(item: Any) -> ComputeEstimate | None:
    if getattr(item, "hosting", None) != "agentarea":
        return None
    reservation = await instance_reservation()
    if reservation is None:
        return None
    priced = await price_compute_hour(vcpu=reservation.vcpu, memory_gib=reservation.memory_gib)
    hourly, currency = priced if priced is not None else (None, None)
    return ComputeEstimate(reservation.vcpu, reservation.memory_gib, hourly, currency)


async def price_catalog_items(items: Sequence[Any]) -> list[CatalogItemPricing | None]:
    """Each entry's pricing, or None for one with no pricing dimension; one quote in all."""
    found: list[tuple[CatalogPricing, tuple[Payer, ...], list[ToolPrice]] | None] = []
    for item in items:
        kind: CatalogPricing | None = item.pricing
        if kind is None:
            found.append(None)
            continue
        metadata = catalog_metadata(item.spec)
        try:
            payers = connector_payers(metadata.get(META_PAYERS))
        except ToolCostError:
            logger.warning("Catalog entry %s declares malformed payers", item.id, exc_info=True)
            found.append(None)
            continue
        found.append((kind, payers, _vendor_costs(item, metadata) if kind == "paid" else []))
    on_platform = [
        (index, _connector(items[index]), cost)
        for index, entry in enumerate(found)
        if entry is not None and Payer.PLATFORM in entry[1]
        for cost in entry[2]
    ]
    priced = await _billing_prices(
        [connector for _, connector, _ in on_platform], [cost for _, _, cost in on_platform]
    )
    by_item: dict[int, list[ToolPrice]] = {}
    for (index, _, _), price in zip(on_platform, priced, strict=True):
        if price is not None:
            by_item.setdefault(index, []).append(price)
    result: list[CatalogItemPricing | None] = []
    for index, (item, entry) in enumerate(zip(items, found, strict=True)):
        if entry is None:
            result.append(None)
            continue
        kind, payers, costs = entry
        prices = by_item.get(index, []) if Payer.PLATFORM in payers else costs
        result.append(
            CatalogItemPricing(kind, payers, tuple(prices), await _compute_estimate(item))
        )
    return result


async def price_catalog_item(item: Any) -> CatalogItemPricing | None:
    """The entry's pricing, or None for an entry that has no pricing dimension."""
    [pricing] = await price_catalog_items([item])
    return pricing
