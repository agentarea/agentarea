"""What a non-chat model call costs the workspace, as billing says it."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.model_charges import charge_model_call
from agentarea_common.money import Money

from agentarea_llm.infrastructure.model_clients import ModelEndpoint


@dataclass(frozen=True)
class PricedCost:
    amount: Money
    currency: str


async def price_model_call(endpoint: ModelEndpoint, *, provider_cost_usd: Decimal) -> PricedCost:
    """A media or decision model call's line amount, from its provider cost in USD.

    Everything downstream (tool results, budgets, task totals) carries the amount
    returned here, unconverted.
    """
    charge = await charge_model_call(
        model_instance_id=endpoint.instance_id,
        platform_funded=endpoint.managed_by == MANAGED_BY_PLATFORM,
        vendor_cost=provider_cost_usd,
        hold=None,
    )
    return PricedCost(amount=charge.amount, currency=charge.currency)
