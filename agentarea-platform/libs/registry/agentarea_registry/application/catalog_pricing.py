"""What using a connections catalog entry costs through AgentArea (wiki ADR-0038).

Whether an entry is paid is a browse facet, derived at sync time from what the
entry declares (``catalog_facets``). What a call costs the workspace is not: on
the platform's key it is the vendor's rate as the installed billing prices it
(markup, currency), so it is asked of the customer pricing seam when the entry is
read. Without enterprise billing that is the vendor's rate in its own currency.

An entry that runs on AgentArea also holds compute while its instance runs. That is
billed per hour of what the instance reserved, separately from any call, so it is a
separate estimate: the reservation as the MCP manager reports it, priced by billing
when one is installed and left unpriced otherwise.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agentarea_common.extensions.customer_pricing import (
    FxUnavailableError,
    price_compute_hour,
    price_vendor_cost,
)
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
    """What the workspace pays per unit of one tool's calls; ``tool`` None is the default."""

    tool: str | None
    amount: Decimal
    currency: str
    unit: str


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
    # Priced on the platform's key; empty unless the entry is paid and declares rates.
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


async def _rate_prices(item: Any, metadata: dict[str, Any]) -> tuple[ToolPrice, ...]:
    cost = metadata.get(META_COST) or {}
    declarations: list[tuple[str | None, Any]] = [
        (None, cost.get("default")),
        *((tool, declaration) for tool, declaration in (cost.get("tools") or {}).items()),
    ]
    connector = _connector(item)
    prices: list[ToolPrice] = []
    for tool, declaration in declarations:
        if declaration is None:
            continue
        try:
            model = parse_cost_model(declaration)
        except ToolCostError:
            logger.warning(
                "Catalog entry %s declares a malformed cost for %s", connector, tool, exc_info=True
            )
            continue
        if model.source is not CostSourceKind.RATE or model.rate_amount is None:
            continue
        try:
            amount, currency = await price_vendor_cost(
                payer=Payer.PLATFORM.value,
                connector=connector,
                tool=tool or "*",
                vendor_cost=model.rate_amount,
                currency=model.currency or "",
            )
        except FxUnavailableError:
            logger.warning("No price for %s#%s on the platform key", connector, tool, exc_info=True)
            continue
        prices.append(ToolPrice(tool, amount, currency, model.unit))
    return tuple(prices)


async def _compute_estimate(item: Any) -> ComputeEstimate | None:
    if getattr(item, "hosting", None) != "agentarea":
        return None
    reservation = await instance_reservation()
    if reservation is None:
        return None
    priced = await price_compute_hour(vcpu=reservation.vcpu, memory_gib=reservation.memory_gib)
    hourly, currency = priced if priced is not None else (None, None)
    return ComputeEstimate(reservation.vcpu, reservation.memory_gib, hourly, currency)


async def price_catalog_item(item: Any) -> CatalogItemPricing | None:
    """The entry's pricing, or None for an entry that has no pricing dimension."""
    kind: CatalogPricing | None = item.pricing
    if kind is None:
        return None
    metadata = catalog_metadata(item.spec)
    try:
        payers = connector_payers(metadata.get(META_PAYERS))
    except ToolCostError:
        logger.warning("Catalog entry %s declares malformed payers", item.id, exc_info=True)
        return None
    prices = await _rate_prices(item, metadata) if kind == "paid" else ()
    return CatalogItemPricing(kind, payers, prices, await _compute_estimate(item))
