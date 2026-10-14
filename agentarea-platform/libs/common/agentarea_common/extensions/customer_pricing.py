"""The currency billing keeps its ledger in, and what an hour of compute costs.

What a model or tool call costs the workspace is billing's live answer
(``tool_billing``, ``model_charges``); nothing here prices a call. This seam names
the billing currency for amounts read back (dashboards, task totals) and estimates
an hour of reserved compute for display. The ``*_usd`` field names on amounts are
kept for API compatibility; their meaning is "billing currency".

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


@runtime_checkable
class ComputePricing(Protocol):
    """A pricing that also knows what an hour of reserved compute costs, for display."""

    async def price_compute_hour(self, *, vcpu: Decimal, memory_gib: Decimal) -> Decimal:
        """Return what one hour of this reservation costs, in ``currency()``.

        An estimate ahead of time; billing is the money authority. Raises a
        ``LookupError`` while billing prices no compute.
        """
        ...


class ProviderCostPricing:
    """OSS default: the customer pays the provider cost, in USD."""

    def currency(self) -> str:
        return "USD"


class CustomerPricingUnavailableError(RuntimeError):
    """An installed customer_pricing extension could not be resolved."""


def resolve_customer_pricing() -> CustomerPricing:
    """Build the active pricing from the registry.

    With no extension registered, the OSS default applies. With one registered,
    it must resolve or nothing is priced: a process that fell back to the USD
    default here would write provider USD into the same totals and budgets that
    its sibling pods are writing billing currency into, and nothing downstream
    can tell the two apart. Raising instead makes the process fail at startup,
    where the orchestrator restarts it and the failure is loud.
    """
    factory = ExtensionRegistry.get_factory(CUSTOMER_PRICING_EXTENSION)
    if factory is None:
        # Installed but failed to import: the same unknown currency as a factory
        # that raises, only earlier. Discovery logged and moved on; here it counts.
        failure = ExtensionRegistry.get_failure(CUSTOMER_PRICING_EXTENSION)
        if failure is not None:
            raise CustomerPricingUnavailableError(
                f"customer_pricing extension is installed but failed to load: {failure}"
            )
        logger.info("No customer_pricing extension registered; amounts are provider cost in USD")
        return ProviderCostPricing()

    try:
        pricing = factory()
    except Exception as error:
        raise CustomerPricingUnavailableError(
            f"customer_pricing extension failed to load: {error}"
        ) from error

    if not isinstance(pricing, CustomerPricing):
        raise CustomerPricingUnavailableError(
            f"customer_pricing extension returned {type(pricing).__name__}, "
            "which is not a CustomerPricing"
        )

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
    one process has to price every call the same way. A failed resolution raises
    and is not cached, so the next use tries again.
    """
    return resolve_customer_pricing()


async def price_compute_hour(
    *,
    vcpu: Decimal,
    memory_gib: Decimal,
    pricing: CustomerPricing | None = None,
) -> tuple[Decimal, str] | None:
    """What an hour of a reservation is expected to cost, and its currency.

    None when nothing prices compute: without an installed billing there is no rate
    to quote, and none is made up.
    """
    active = pricing or get_customer_pricing()
    if not isinstance(active, ComputePricing):
        return None
    try:
        amount = await active.price_compute_hour(vcpu=vcpu, memory_gib=memory_gib)
    except LookupError:
        logger.debug("Reserved compute is not priced by %s", type(active).__name__, exc_info=True)
        return None
    return to_money(amount), active.currency()
