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
"""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

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
class ModelCharge:
    """A model call's spend line: its amount and how it is still to be settled."""

    amount: Money
    currency: str
    vendor_cost: Money
    vendor_currency: str = PROVIDER_CURRENCY
    estimate: bool = False
    settle: str | None = None
    hold_id: str | None = None

    def evidence(self) -> dict[str, Any]:
        """What the ledger line keeps for its settlement: the hold and what is pending."""
        return {
            key: value
            for key, value in {"hold_id": self.hold_id, "settle": self.settle}.items()
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
        }


async def hold_model_call(
    *,
    workspace_id: str,
    model_instance_id: str,
    platform_funded: bool,
    vendor_cost_estimate: Decimal,
    idempotency_key: str,
) -> Any | None:
    """Billing's hold for a call on the platform's credentials, or None when none is needed.

    Raises ``ModelCallRefusedError`` when billing refuses or cannot answer.
    """
    if not platform_funded:
        return None
    billing, failure = tool_billing.usable_tool_billing()
    if failure is not None:
        raise ModelCallRefusedError("billing_unavailable", failure)
    if billing is None:
        return None
    try:
        hold = await tool_billing.billing_call(
            "authorize",
            billing.authorize(
                workspace_id=workspace_id,
                connector=MODEL_CONNECTOR,
                tool=model_instance_id,
                vendor_cost=vendor_cost_estimate,
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
    return hold


async def release_model_hold(hold: Any, why: str) -> None:
    """Void a hold whose call did not run to an answer; a failure leaves it to its TTL."""
    if hold is None:
        return
    billing, _ = tool_billing.usable_tool_billing()
    if billing is None:
        logger.error("Hold %s (%s) cannot be voided: billing is not usable", hold.hold_id, why)
        return
    try:
        await tool_billing.billing_call("void", billing.void(hold_id=str(hold.hold_id)))
    except Exception:
        logger.error(
            "Hold %s (%s) could not be voided; it expires", hold.hold_id, why, exc_info=True
        )


async def charge_model_call(
    *,
    model_instance_id: str,
    platform_funded: bool,
    vendor_cost: Decimal,
    hold: Any | None,
) -> ModelCharge:
    """The line one finished model call writes, from its vendor cost in USD."""
    vendor_cost = to_money(vendor_cost)
    if hold is not None:
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
            else (to_money(hold.amount), str(hold.currency))
        )
        return ModelCharge(
            amount=amount,
            currency=currency,
            vendor_cost=vendor_cost,
            estimate=True,
            settle=SETTLE_CAPTURE,
            hold_id=str(hold.hold_id),
        )
    if platform_funded:
        billing, failure = tool_billing.usable_tool_billing()
        if failure is not None:
            raise ModelChargeUnavailableError(failure)
        if billing is None:
            # The platform's credentials and no billing (a self-hosted shared key):
            # the vendor cost is what the deployment spends, in USD.
            return ModelCharge(
                amount=vendor_cost, currency=PROVIDER_CURRENCY, vendor_cost=vendor_cost
            )
        # A call billing held nothing for (a media model, whose cost is known only
        # afterwards): billing prices it now, or the call fails as unaccounted.
        line = tool_billing.QuoteLine(
            payer="platform",
            connector=MODEL_CONNECTOR,
            tool=model_instance_id,
            vendor_cost=vendor_cost,
            vendor_currency=PROVIDER_CURRENCY,
            kind=tool_billing.KIND_MODEL,
        )
        try:
            [quote] = await tool_billing.billing_call("quote", billing.quote([line]))
        except Exception as error:
            raise ModelChargeUnavailableError(
                f"billing could not price the call: {error}"
            ) from error
        if quote.amount is None:
            raise ModelChargeUnavailableError(
                f"billing does not price model {model_instance_id} ({quote.code})"
            )
        return ModelCharge(
            amount=to_money(quote.amount), currency=billing.currency(), vendor_cost=vendor_cost
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
        amount=to_money(converted.amount),
        currency=converted.currency,
        vendor_cost=vendor_cost,
        estimate=converted.pending,
        settle=SETTLE_CONVERT if converted.pending else None,
    )
