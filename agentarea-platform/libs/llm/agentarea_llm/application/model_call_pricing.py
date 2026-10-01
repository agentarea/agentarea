"""What a non-chat model call costs the customer, in the billing currency."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.extensions.customer_pricing import (
    CustomerPricing,
    get_customer_pricing,
    price_llm_call,
)
from agentarea_common.money import Money

from agentarea_llm.infrastructure.model_clients import ModelEndpoint


@dataclass(frozen=True)
class PricedCost:
    amount: Money
    currency: str


async def price_model_call(
    endpoint: ModelEndpoint,
    *,
    provider_cost_usd: Decimal,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    pricing: CustomerPricing | None = None,
) -> PricedCost:
    """Convert a call's provider cost once, through the same seam LLM calls use.

    Everything downstream (tool results, budgets, task totals) carries the amount
    returned here, unconverted.
    """
    amount = await price_llm_call(
        model_instance_id=endpoint.instance_id,
        platform_funded=endpoint.managed_by == MANAGED_BY_PLATFORM,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        provider_cost_usd=provider_cost_usd,
        pricing=pricing,
    )
    return PricedCost(amount=amount, currency=(pricing or get_customer_pricing()).currency())
