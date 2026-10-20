"""The billing that charges platform-paid tool calls, asked live (wiki ADR-0038 §2.4).

The platform knows what a tool call cost the payer, never what the customer is
charged for it. A call on the platform's key is authorised against the workspace's
balance before it runs: billing places a hold for the customer amount of the estimated
vendor cost and returns it. After the call the hold is captured with the actual vendor
cost (billing rates, debits and releases the rest) or voided. ``quote`` asks billing to
express a vendor cost in the ledger currency, for display and for a foreign-currency
cost on the customer's own key. Nothing here is cached: every answer is billing's own,
at the moment it is asked.

Additive extension point: without one installed, nothing is held or charged, a
platform-managed connection is governed by policy and caps alone, and the deployment
currency is ``AGENTAREA_SPEND_CURRENCY``. Installed, its ledger currency is the
deployment currency, and a process whose ``AGENTAREA_SPEND_CURRENCY`` disagrees refuses
to start.

The protocol is structural: an extension returns any objects with the attributes
named below. ``kind`` says what is bought: ``tool`` (a connector's tool) or ``model``
(an inference call on a model instance, ``tool`` then naming the instance).

Every round trip is bounded by ``BILLING_TIMEOUT`` and its latency logged.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from functools import cache
from typing import Any, Protocol, runtime_checkable

from ..config.spend import get_spend_currency
from .registry import ExtensionRegistry

logger = logging.getLogger(__name__)

TOOL_BILLING_EXTENSION = "tool_billing"
# How long one billing round trip may take before the caller treats billing as down.
BILLING_TIMEOUT = 5.0
KIND_TOOL = "tool"
KIND_MODEL = "model"


@runtime_checkable
class HoldDecision(Protocol):
    """Billing's answer to authorize.

    ``allowed`` with a ``hold_id`` and the held ``amount`` in ``currency`` (the ledger
    currency); otherwise ``code`` (``no_credits``, ``tool_unpriced``,
    ``account_unresolved``, ``credit_limit_reached``) and ``reason``.
    """

    allowed: bool
    code: str
    reason: str
    hold_id: str | None
    amount: Decimal | None
    currency: str | None
    expires_at: datetime | None


@runtime_checkable
class Charge(Protocol):
    """What a capture charged, in the ledger currency."""

    amount: Decimal
    currency: str


@dataclass(frozen=True)
class QuoteLine:
    """A vendor cost to express in the ledger currency; ``payer`` platform adds markup."""

    payer: str
    connector: str
    tool: str
    vendor_cost: Decimal
    vendor_currency: str
    kind: str = KIND_TOOL


@runtime_checkable
class Quote(Protocol):
    """One line's amount in the ledger currency, or None with why.

    ``code`` is ``ok``, ``tool_unpriced`` or ``fx_unavailable``.
    """

    amount: Decimal | None
    code: str


@runtime_checkable
class ToolBilling(Protocol):
    def currency(self) -> str:
        """The ledger currency, ISO 4217."""
        ...

    async def authorize(
        self,
        *,
        workspace_id: str,
        connector: str,
        tool: str,
        vendor_cost: Decimal,
        vendor_currency: str,
        quantity: Decimal,
        unit: str,
        idempotency_key: str,
        kind: str = KIND_TOOL,
    ) -> HoldDecision:
        """Hold the customer amount of an estimated vendor cost, or refuse.

        Raises when billing cannot answer; the caller refuses the call.
        """
        ...

    async def capture(
        self,
        *,
        hold_id: str,
        workspace_id: str,
        connector: str,
        tool: str,
        vendor_cost: Decimal,
        vendor_currency: str,
        quantity: Decimal,
        unit: str,
        idempotency_key: str,
        metadata: dict[str, Any],
        kind: str = KIND_TOOL,
    ) -> Charge:
        """Charge the actual vendor cost against a hold and release the rest.

        Idempotent on ``idempotency_key``; charges even after the hold expired.
        """
        ...

    async def void(self, *, hold_id: str) -> None:
        """Release a hold whose call did not run. Idempotent."""
        ...

    async def quote(self, lines: Sequence[QuoteLine]) -> Sequence[Quote]:
        """Each line in the ledger currency, in order."""
        ...


class ToolBillingUnavailableError(RuntimeError):
    """An installed tool_billing extension could not be resolved."""


class SpendCurrencyMismatchError(RuntimeError):
    """AGENTAREA_SPEND_CURRENCY names another currency than billing's ledger."""


def resolve_tool_billing() -> ToolBilling | None:
    """The installed billing, None without one; installed but broken raises."""
    factory = ExtensionRegistry.get_factory(TOOL_BILLING_EXTENSION)
    if factory is None:
        failure = ExtensionRegistry.get_failure(TOOL_BILLING_EXTENSION)
        if failure is not None:
            raise ToolBillingUnavailableError(
                f"tool_billing extension is installed but failed to load: {failure}"
            )
        return None
    try:
        billing = factory()
    except Exception as error:
        raise ToolBillingUnavailableError(
            f"tool_billing extension failed to load: {error}"
        ) from error
    if not isinstance(billing, ToolBilling):
        raise ToolBillingUnavailableError(
            f"tool_billing extension returned {type(billing).__name__}, which is not a ToolBilling"
        )
    configured = get_spend_currency()
    if billing.currency() != configured:
        raise SpendCurrencyMismatchError(
            f"billing keeps its ledger in {billing.currency()} but "
            f"AGENTAREA_SPEND_CURRENCY is {configured}; set it to {billing.currency()}"
        )
    logger.info("Tool billing from extension: %s", type(billing).__name__)
    return billing


@cache
def get_tool_billing() -> ToolBilling | None:
    """The process-wide billing, resolved on first use (after extension discovery).

    A failed resolution raises and is not cached, so the next use tries again.
    """
    return resolve_tool_billing()


def deployment_currency() -> str:
    """The currency caps count and lines are expressed in: billing's ledger, else the env."""
    billing = get_tool_billing()
    return billing.currency() if billing is not None else get_spend_currency()


def usable_tool_billing() -> tuple[ToolBilling | None, str | None]:
    """The installed billing, or why an installed one cannot be used."""
    try:
        return get_tool_billing(), None
    except (ToolBillingUnavailableError, SpendCurrencyMismatchError) as error:
        logger.error("Tool billing is installed but unusable", exc_info=True)
        return None, str(error)


async def billing_call[T](name: str, call: Awaitable[T]) -> T:
    """One billing round trip, bounded by ``BILLING_TIMEOUT``, its latency logged."""
    started = time.monotonic()
    try:
        return await asyncio.wait_for(call, timeout=BILLING_TIMEOUT)
    finally:
        logger.info("Billing %s took %.0f ms", name, (time.monotonic() - started) * 1000)


@dataclass(frozen=True)
class Converted:
    """A cost as its line's amount: in the deployment currency, or left in its own."""

    amount: Decimal
    currency: str
    # Billing could not answer; the settlement worker converts it later.
    pending: bool = False


async def convert_cost(
    *,
    payer: str,
    connector: str,
    tool: str,
    vendor_cost: Decimal,
    vendor_currency: str,
    kind: str = KIND_TOOL,
) -> Converted:
    """A cost on the payer's own money in the deployment currency, without markup.

    As is when it is in that currency; converted by billing otherwise. Without
    billing nothing converts it, and the line keeps the vendor's currency, which
    caps in the deployment currency do not cover.
    """
    currency = deployment_currency()
    if vendor_currency == currency:
        return Converted(vendor_cost, currency)
    billing, _ = usable_tool_billing()
    if billing is None:
        return Converted(vendor_cost, vendor_currency)
    line = QuoteLine(
        payer="workspace",
        connector=connector,
        tool=tool,
        vendor_cost=vendor_cost,
        vendor_currency=vendor_currency,
        kind=kind,
    )
    try:
        [quote] = await billing_call("quote", billing.quote([line]))
    except Exception:
        logger.error(
            "A %s cost of %s#%s (%s) could not be converted to %s now; left for settlement",
            vendor_currency,
            connector,
            tool,
            payer,
            currency,
            exc_info=True,
        )
        return Converted(vendor_cost, vendor_currency, pending=True)
    if quote.amount is None:
        logger.warning(
            "Billing cannot express a %s cost of %s#%s in %s (%s); not covered by caps",
            vendor_currency,
            connector,
            tool,
            currency,
            quote.code,
        )
        return Converted(vendor_cost, vendor_currency)
    return Converted(quote.amount, currency)
