"""What a model call costs the workspace, as billing says it (wiki ADR-0038 rev 2).

The platform knows what the provider charged for a call (the provider's reported cost,
or the declared per-token rates, cached and cache-creation tokens included), in USD.
It never prices a call itself:

- On the platform's credentials with billing installed, billing holds the customer
  amount of an estimated vendor cost before the call (``hold_model_call``), and right
  after it says what the actual vendor cost comes to (``charge_model_call``). The line
  carries the hold, which the settlement worker captures. When billing cannot say, the
  line carries the held amount instead, still to be captured; never the vendor cost
  as if it were the customer's price.
- On the customer's own credentials the amount is the vendor cost, converted by
  billing when the deployment currency is not USD; without billing it stays in USD,
  not covered by caps in another currency.

Every model call starts with ``hold_model_call``, whatever its surface (a run, a
trigger condition, a media tool): its ``ModelFunding`` is what the platform's
credential is read with, so a call on the platform's key cannot run unheld.
"""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .constants import MANAGED_BY_PLATFORM
from .extensions import tool_billing
from .money import Money, to_money

logger = logging.getLogger(__name__)

PROVIDER_CURRENCY = "USD"
# The connector a model call is bought under; the model instance is its "tool".
MODEL_CONNECTOR = "llm"
SETTLE_CAPTURE = "capture"
SETTLE_CONVERT = "convert"


def estimate_vendor_cost(
    messages: list[Any],
    max_tokens: int | None,
    input_cost_per_token: Any,
    output_cost_per_token: Any,
) -> Money:
    """The most a call can cost the payer: its prompt, roughly, and every output token."""
    prompt_tokens = len(json.dumps(messages, default=str)) // 4
    return to_money(
        prompt_tokens * to_money(input_cost_per_token)
        + (max_tokens or 0) * to_money(output_cost_per_token)
    )


class ModelChargeUnavailableError(RuntimeError):
    """A finished call on the platform's credentials that billing could not price.

    The message marks it an accounting error, which the activity layer does not retry:
    a retry would pay the provider again for a call that was already answered.
    """

    def __init__(self, detail: str):
        super().__init__(f"model usage accounting unavailable: {detail}")


class ModelCallRefusedError(Exception):
    """Billing will not hold this call: ``code`` says why (no_credits, model_unpriced, ...)."""

    def __init__(self, code: str, reason: str):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class ModelFunding:
    """Who pays one model call, settled before its credential is read.

    Only ``hold_model_call`` makes one (or ``restore`` brings back one it made, for
    a call that finishes later, like a video job). ``hold_id`` is set when billing
    holds the call on the platform's credentials; ``held_amount`` is then what the
    line comes to if the call's actual cost is never known.
    """

    model_instance_id: str
    platform_funded: bool
    hold_id: str | None = None
    held_amount: Money | None = None
    held_currency: str | None = None
    vendor_cost_estimate: Money | None = None

    def stored(self) -> dict[str, Any]:
        """What a row keeps to finish the call later with ``restore``."""
        return {
            "model_instance_id": self.model_instance_id,
            "platform_funded": self.platform_funded,
            "hold_id": self.hold_id,
            "held_amount": None if self.held_amount is None else str(self.held_amount),
            "held_currency": self.held_currency,
            "vendor_cost_estimate": (
                None if self.vendor_cost_estimate is None else str(self.vendor_cost_estimate)
            ),
        }

    @classmethod
    def restore(cls, stored: dict[str, Any]) -> ModelFunding:
        return cls(
            model_instance_id=str(stored["model_instance_id"]),
            platform_funded=bool(stored["platform_funded"]),
            hold_id=stored.get("hold_id"),
            held_amount=(
                None if stored.get("held_amount") is None else to_money(stored["held_amount"])
            ),
            held_currency=stored.get("held_currency"),
            vendor_cost_estimate=(
                None
                if stored.get("vendor_cost_estimate") is None
                else to_money(stored["vendor_cost_estimate"])
            ),
        )


class UnfundedPlatformCallError(RuntimeError):
    """The platform's credential was asked for without a funding for the call."""


def require_funding(funding: ModelFunding | None, managed_by: str | None) -> None:
    """Refuse the platform's credential to a call ``hold_model_call`` did not fund."""
    if managed_by != MANAGED_BY_PLATFORM:
        return
    if funding is None or not funding.platform_funded:
        raise UnfundedPlatformCallError(
            "a call on the platform's credentials must be held by billing before its "
            "credential is read"
        )


@dataclass(frozen=True)
class ModelCharge:
    """A model call's spend line: its amount and how it is still to be settled."""

    amount: Money
    currency: str
    vendor_cost: Money
    vendor_currency: str = PROVIDER_CURRENCY
    estimate: bool = False
    settle: str | None = None
    hold_id: str | None = None
    # The provider was paid but said nothing of what for: on a hold the line is the
    # held amount; otherwise it records the call at no amount.
    cost_unknown: bool = False
    platform_funded: bool = False
    model_instance_id: str | None = None

    def evidence(self) -> dict[str, Any]:
        """What the ledger line keeps for its settlement: the hold and what is pending."""
        return {
            key: value
            for key, value in {
                "hold_id": self.hold_id,
                "settle": self.settle,
                "cost_unknown": self.cost_unknown or None,
            }.items()
            if value is not None
        }

    def as_billing(self) -> dict[str, Any]:
        """What the call's ``llm.call.completed`` event carries for its ledger line."""
        return {
            "amount": str(self.amount),
            "currency": self.currency,
            "vendor_cost": str(self.vendor_cost),
            "vendor_currency": self.vendor_currency,
            "estimate": self.estimate,
            "settle": self.settle,
            "hold_id": self.hold_id,
            "cost_unknown": self.cost_unknown,
            "payer": "platform" if self.platform_funded else "workspace",
            "model_instance_id": self.model_instance_id,
        }


async def hold_model_call(
    *,
    workspace_id: str,
    model_instance_id: str,
    managed_by: str | None,
    vendor_cost_estimate: Decimal | None,
    idempotency_key: str,
) -> ModelFunding:
    """Fund one model call before it runs: billing's hold when the platform pays.

    ``vendor_cost_estimate`` is the most the call can cost in USD; None when the model
    declares no price to estimate it by, which billing cannot hold against.
    Raises ``ModelCallRefusedError`` when billing refuses or cannot answer.
    """
    platform_funded = managed_by == MANAGED_BY_PLATFORM
    funding = ModelFunding(model_instance_id=model_instance_id, platform_funded=platform_funded)
    if not platform_funded:
        return funding
    billing, failure = tool_billing.usable_tool_billing()
    if failure is not None:
        raise ModelCallRefusedError("billing_unavailable", failure)
    if billing is None:
        return funding
    if vendor_cost_estimate is None:
        raise ModelCallRefusedError(
            "model_unpriced",
            f"model {model_instance_id} declares no price to hold a call on the "
            "platform's credentials against",
        )
    estimate = to_money(vendor_cost_estimate)
    try:
        hold = await tool_billing.billing_call(
            "authorize",
            billing.authorize(
                workspace_id=workspace_id,
                connector=MODEL_CONNECTOR,
                tool=model_instance_id,
                vendor_cost=estimate,
                vendor_currency=PROVIDER_CURRENCY,
                quantity=Decimal(1),
                unit="call",
                idempotency_key=idempotency_key,
                kind=tool_billing.KIND_MODEL,
            ),
        )
    except Exception as error:
        logger.error("Billing could not authorize model %s", model_instance_id, exc_info=True)
        raise ModelCallRefusedError(
            "billing_unavailable", "billing is temporarily unavailable"
        ) from error
    if not hold.allowed:
        raise ModelCallRefusedError(str(hold.code), str(hold.reason))
    return ModelFunding(
        model_instance_id=model_instance_id,
        platform_funded=True,
        hold_id=str(hold.hold_id),
        held_amount=to_money(hold.amount),
        held_currency=str(hold.currency),
        vendor_cost_estimate=estimate,
    )


async def release_model_hold(funding: ModelFunding | None, why: str) -> None:
    """Void the hold of a call that did not run to an answer; a failure leaves it to its TTL."""
    if funding is None or funding.hold_id is None:
        return
    billing, _ = tool_billing.usable_tool_billing()
    if billing is None:
        logger.error("Hold %s (%s) cannot be voided: billing is not usable", funding.hold_id, why)
        return
    try:
        await tool_billing.billing_call("void", billing.void(hold_id=funding.hold_id))
    except Exception:
        logger.error(
            "Hold %s (%s) could not be voided; it expires", funding.hold_id, why, exc_info=True
        )


async def charge_model_call(*, funding: ModelFunding, vendor_cost: Decimal | None) -> ModelCharge:
    """The line one finished model call writes, from its vendor cost in USD.

    ``vendor_cost`` is None when the provider was paid but reported no cost: a held
    call then comes to its held amount, captured at the estimated vendor cost.
    """
    model_instance_id = funding.model_instance_id
    if funding.hold_id is not None:
        if vendor_cost is None:
            logger.error(
                "Model %s reported no cost; its line is the held amount", model_instance_id
            )
            return ModelCharge(
                model_instance_id=model_instance_id,
                amount=to_money(funding.held_amount),
                currency=str(funding.held_currency),
                vendor_cost=to_money(funding.vendor_cost_estimate),
                estimate=True,
                settle=SETTLE_CAPTURE,
                hold_id=funding.hold_id,
                cost_unknown=True,
                platform_funded=True,
            )
        vendor_cost = to_money(vendor_cost)
        billing, _ = tool_billing.usable_tool_billing()
        line = tool_billing.QuoteLine(
            payer="platform",
            connector=MODEL_CONNECTOR,
            tool=model_instance_id,
            vendor_cost=vendor_cost,
            vendor_currency=PROVIDER_CURRENCY,
            kind=tool_billing.KIND_MODEL,
        )
        quoted = None
        if billing is not None:
            try:
                [quote] = await tool_billing.billing_call("quote", billing.quote([line]))
                quoted = quote.amount
                if quoted is None:
                    logger.error(
                        "Billing does not price model %s it held (%s); the line keeps the hold",
                        model_instance_id,
                        quote.code,
                    )
            except Exception:
                logger.error(
                    "Billing could not price model %s now; the line keeps its hold",
                    model_instance_id,
                    exc_info=True,
                )
        amount, currency = (
            (to_money(quoted), billing.currency())
            if quoted is not None and billing is not None
            else (to_money(funding.held_amount), str(funding.held_currency))
        )
        return ModelCharge(
            model_instance_id=model_instance_id,
            amount=amount,
            currency=currency,
            vendor_cost=vendor_cost,
            estimate=True,
            settle=SETTLE_CAPTURE,
            hold_id=funding.hold_id,
            platform_funded=True,
        )
    if vendor_cost is None:
        # Nobody's money is held: the customer's own key, or the platform's key on a
        # deployment without billing. The line records the call at no amount.
        logger.error("Model %s reported no cost; its cost is unknown", model_instance_id)
        return ModelCharge(
            model_instance_id=model_instance_id,
            amount=to_money(0),
            currency=PROVIDER_CURRENCY,
            vendor_cost=to_money(0),
            estimate=True,
            cost_unknown=True,
            platform_funded=funding.platform_funded,
        )
    vendor_cost = to_money(vendor_cost)
    if funding.platform_funded:
        billing, failure = tool_billing.usable_tool_billing()
        if failure is not None:
            raise ModelChargeUnavailableError(failure)
        if billing is not None:
            raise ModelChargeUnavailableError(
                f"model {model_instance_id} ran on the platform's credentials without a hold"
            )
        # The platform's credentials and no billing (a self-hosted shared key):
        # the vendor cost is what the deployment spends, in USD.
        return ModelCharge(
            model_instance_id=model_instance_id,
            amount=vendor_cost,
            currency=PROVIDER_CURRENCY,
            vendor_cost=vendor_cost,
            platform_funded=True,
        )
    converted = await tool_billing.convert_cost(
        payer="workspace",
        connector=MODEL_CONNECTOR,
        tool=model_instance_id,
        vendor_cost=vendor_cost,
        vendor_currency=PROVIDER_CURRENCY,
        kind=tool_billing.KIND_MODEL,
    )
    return ModelCharge(
        model_instance_id=model_instance_id,
        amount=to_money(converted.amount),
        currency=converted.currency,
        vendor_cost=vendor_cost,
        estimate=converted.pending,
        settle=SETTLE_CONVERT if converted.pending else None,
    )
