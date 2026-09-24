"""What the customer pays for an LLM call, in the billing account's currency.

The platform knows what a call cost the provider, in USD. What the customer is
charged is decided by billing — its currency, its exchange rate, its per-model
price — and that declaration lives once, on the billing side. This module is the
seam through which the platform asks, so it never re-declares any of it.

Every amount downstream of an LLM call (task totals, events, dashboards, budget
and cap enforcement) is converted here, at one point, and carried as-is from then
on. The ``*_usd`` field names on those amounts are kept for API compatibility;
their meaning is "billing currency", which ``CustomerPricing.currency()`` names.

Additive extension point (see AGENTS.md → EXTENSION POINTS): there is no config
that selects a pricing backend, so an installed ``customer_pricing`` extension is
active by being installed. Without one, the OSS default applies: USD, and the
customer pays the provider cost — which is exactly the behaviour before this seam
existed.
"""

import logging
from decimal import Decimal
from functools import cache
from typing import Protocol, runtime_checkable

from ..money import to_money
from .registry import ExtensionRegistry

logger = logging.getLogger(__name__)

CUSTOMER_PRICING_EXTENSION = "customer_pricing"


@runtime_checkable
class CustomerPricing(Protocol):
    def currency(self) -> str:
        """ISO 4217 code every priced amount is denominated in, e.g. ``"RUB"``."""
        ...

    async def price_llm_call(
        self,
        *,
        model_instance_id: str | None,
        platform_funded: bool,
        prompt_tokens: int,
        completion_tokens: int,
        provider_cost_usd: Decimal,
    ) -> Decimal:
        """Return what this call costs the customer, in ``currency()``.

        ``platform_funded`` is True when the call ran on the operator's credentials
        (the customer buys the tokens from us), False when it ran on the customer's
        own key (the provider bills them; any amount here is an estimate).
        """
        ...


class ProviderCostPricing:
    """OSS default: the customer pays the provider cost, in USD."""

    def currency(self) -> str:
        return "USD"

    async def price_llm_call(
        self,
        *,
        model_instance_id: str | None,
        platform_funded: bool,
        prompt_tokens: int,
        completion_tokens: int,
        provider_cost_usd: Decimal,
    ) -> Decimal:
        return provider_cost_usd


def resolve_customer_pricing() -> CustomerPricing:
    """Build the active pricing from the registry, falling back to the default.

    A failing factory must not take the process down with it: the registry is
    populated by scanning installed packages, so a broken extension is a
    deployment problem, and refusing to start turns "amounts are in USD" into
    "nothing runs". It is logged at error because the fallback is not harmless —
    amounts are then provider USD cost on a deployment whose customers pay in
    something else — and that has to be visible, not discovered from an invoice.
    """
    factory = ExtensionRegistry.get_factory(CUSTOMER_PRICING_EXTENSION)
    if factory is None:
        logger.info("No customer_pricing extension registered; amounts are provider cost in USD")
        return ProviderCostPricing()

    try:
        pricing = factory()
    except Exception:
        logger.exception(
            "customer_pricing extension failed to load; falling back to provider cost in USD"
        )
        return ProviderCostPricing()

    if not isinstance(pricing, CustomerPricing):
        logger.error(
            "customer_pricing extension returned %s, which is not a CustomerPricing; "
            "falling back to provider cost in USD",
            type(pricing).__name__,
        )
        return ProviderCostPricing()

    logger.info("Customer pricing from extension: %s", type(pricing).__name__)
    return pricing


@cache
def get_customer_pricing() -> CustomerPricing:
    """The process-wide pricing, resolved on first use.

    Resolved lazily rather than at import or construction time because callers
    are built before discovery runs — the worker creates its activities (and the
    LLM execution service with them) before ``discover_extensions()``. Resolving
    then would find an empty registry and pin the default for the process
    lifetime, silently. First use is always a request or an activity, both of
    which happen after startup has discovered extensions.

    Cached because it is resolved per call site on the hot path, and because
    one process has to price every call the same way.
    """
    return resolve_customer_pricing()


async def price_llm_call(
    *,
    model_instance_id: str | None,
    platform_funded: bool,
    prompt_tokens: int,
    completion_tokens: int,
    provider_cost_usd: Decimal,
    pricing: CustomerPricing | None = None,
) -> Decimal:
    """What one finished LLM call costs the customer — the only conversion point.

    Every path that makes an LLM call and counts its cost against a budget or a
    task total goes through here, once, as the call returns; nothing after it
    converts again. Two paths converting differently, or one not converting at
    all, would sum RUB and USD into one total.

    A pricing failure fails the call rather than falling back to the USD provider
    cost: that number would be read as billing currency by every budget and total
    after this, so an outage would mis-charge silently. The message marks it an
    accounting error, which the activity layer does not retry — a retry would pay
    the provider again for a call that was already answered.
    """
    active = pricing or get_customer_pricing()
    try:
        return to_money(
            await active.price_llm_call(
                model_instance_id=model_instance_id,
                platform_funded=platform_funded,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                provider_cost_usd=provider_cost_usd,
            )
        )
    except Exception as error:
        raise RuntimeError(
            f"LLM usage accounting unavailable: customer pricing failed: {error}"
        ) from error
