"""The one layer every tool call passes, from a run's tool activity or from /mcp.

In order (wiki ADR-0038):

1. The policy verdict: the runtime PDP (``authorize_tool_invocation``), the same
   answer disclosure and the workflow gate read. A held call returns to its caller,
   whose transport asks a person (a run's escalation, an /mcp approval link) and
   calls again once it is approved.
2. What the call will cost before it runs: a rate on a constant or an argument, else
   the connector's declared estimate.
3. For a call on the platform's key with billing installed, a hold: billing holds
   what it will charge for that cost, or refuses. The platform never prices a call.
4. The spend gate: the caller's caps over the spend ledger (agent, workspace, client,
   connection, tool), told what the call will cost in the deployment currency.
5. The call. A hold whose call did not run, failed or was already metered is voided.
6. The meter: one line per known cost, through the caller's ``ledger``, keyed on the
   tool call so a retry writes it once. A platform line carries the held amount and
   the hold, which the settlement worker captures; a cost in another currency is
   converted by billing, or left in its own currency and not covered by caps.

Each path keeps its own audit trail and passes it in; the layer reports every verdict
it reaches, including a refusal by a gate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationDecision,
    ToolAuthorizationRequest,
    authorize_tool_invocation,
)
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.tool_billing import Converted
from agentarea_common.money import ZERO, to_money
from agentarea_common.tool_cost import (
    CostSourceKind,
    MeteredCost,
    Payer,
    ToolConnection,
    ToolCostError,
    meter,
    pre_call_cost,
)

logger = logging.getLogger(__name__)

WALLET_CURRENCY = "USD"
_PAYMENT_EVIDENCE_KEYS = ("protocol", "recipient", "tx_hash")
# What a line still needs before its figure is final, in ``evidence["settle"]``.
SETTLE_CAPTURE = "capture"
SETTLE_VENDOR = "vendor"
SETTLE_CONVERT = "convert"


@dataclass(frozen=True)
class GovernedToolCall:
    authorization: ToolAuthorizationRequest
    call_id: str
    agent_id: UUID | None
    task_id: str | None
    client_id: str | None = None
    connection: ToolConnection | None = None
    approval_granted: bool = False


@dataclass(frozen=True)
class ToolCallOutcome:
    """What a call returned: its value for the caller, and what the meter reads.

    ``body`` is the decoded response, ``meta`` an MCP result's ``_meta``, and
    ``payments`` the wallet payments the call made. ``replayed`` says the answer is
    one given before: the server served it from its cache, or a payment had already
    settled.
    """

    success: bool
    value: Any = None
    body: Any = None
    meta: dict[str, Any] | None = None
    payments: tuple[dict[str, Any], ...] = ()
    replayed: bool = False


@dataclass(frozen=True)
class ToolUsage:
    """One metered line: what a call cost, whom, and the amount caps count.

    ``estimate`` says ``amount`` is not final yet: a rate from a public price list, a
    held amount billing has not captured, or a cost still to be settled or converted.
    """

    line_key: str
    call_id: str
    workspace_id: str
    user_id: str
    agent_id: UUID | None
    task_id: str | None
    client_id: str | None
    tool_name: str
    connection_id: str | None
    connector: str | None
    tool: str | None
    payer: Payer
    source: CostSourceKind
    quantity: Decimal
    unit: str
    vendor_cost: Decimal
    vendor_currency: str
    amount: Decimal
    currency: str
    occurred_at: datetime
    estimate: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


class Verdict(StrEnum):
    RAN = "ran"
    DENIED = "denied"
    HELD = "held"


@dataclass(frozen=True)
class ToolCallResult:
    verdict: Verdict
    decision: ToolAuthorizationDecision
    outcome: ToolCallOutcome | None = None
    usages: tuple[ToolUsage, ...] = ()
    metered: bool = False
    # The call's lines were already in the ledger, or its answer is one given before.
    replayed: bool = False
    # The deployment currency the run budget counts in.
    currency: str | None = None

    @property
    def cost(self) -> Decimal:
        """The run-budget amount of the call: its lines in the deployment currency.

        A wallet payment is the wallet's, and a cost left in another currency is not
        covered by any budget.
        """
        return sum(
            (
                u.amount
                for u in self.usages
                if u.payer is not Payer.PER_CALL and u.currency == self.currency
            ),
            ZERO,
        )


AuditHook = Callable[[ToolAuthorizationDecision], Awaitable[None]]
# Returns how many lines it inserted (a line already stored is not), or None if unknown.
UsageLedger = Callable[[list[ToolUsage]], Awaitable[int | None]]
# What the call will cost, in a currency, when that is known before it runs.
PendingCost = tuple[Decimal, str]
SpendGate = Callable[[GovernedToolCall, PendingCost | None], Awaitable[str | None]]


def _denied(reason: str) -> ToolAuthorizationDecision:
    return ToolAuthorizationDecision(ToolAuthorizationAction.DENY, reason)


def _billing() -> tuple[tool_billing.ToolBilling | None, str | None]:
    return tool_billing.usable_tool_billing()


async def convert_cost(payer: Payer, connector: str, tool: str, cost: MeteredCost) -> Converted:
    """A tool cost in the deployment currency; see ``tool_billing.convert_cost``."""
    converted = await tool_billing.convert_cost(
        payer=payer.value,
        connector=connector,
        tool=tool,
        vendor_cost=cost.vendor_cost,
        vendor_currency=cost.currency,
    )
    return Converted(to_money(converted.amount), converted.currency, converted.pending)


def _usage(
    call: GovernedToolCall,
    *,
    line_key: str,
    payer: Payer,
    cost: MeteredCost,
    amount: Decimal,
    currency: str,
    connection: ToolConnection | None,
    estimate: bool,
    evidence: dict[str, Any],
) -> ToolUsage:
    request = call.authorization
    return ToolUsage(
        line_key=line_key,
        call_id=call.call_id,
        workspace_id=str(request.workspace_id or ""),
        user_id=str(request.user_id or ""),
        agent_id=call.agent_id,
        task_id=call.task_id,
        client_id=call.client_id,
        tool_name=request.tool_name,
        connection_id=connection.connection_id if connection else None,
        connector=connection.connector if connection else None,
        tool=connection.tool if connection else None,
        payer=payer,
        source=cost.source,
        quantity=cost.quantity,
        unit=cost.unit,
        vendor_cost=cost.vendor_cost,
        vendor_currency=cost.currency,
        amount=amount,
        currency=currency,
        occurred_at=datetime.now(UTC),
        estimate=estimate,
        evidence=evidence,
    )


@dataclass(frozen=True)
class _Before:
    """What the layer learnt before the call: its cost, as converted, and any hold."""

    cost: MeteredCost | None = None
    converted: Converted | None = None
    hold: Any = None


async def _connection_line(
    call: GovernedToolCall,
    connection: ToolConnection,
    outcome: ToolCallOutcome,
    before: _Before,
) -> ToolUsage | None:
    try:
        cost = meter(
            connection.cost_model,
            args=dict(call.authorization.tool_args),
            body=outcome.body,
            meta=outcome.meta,
        )
    except ToolCostError:
        if before.hold is None:
            logger.error(
                "Tool call %s on %s could not be metered; no line recorded",
                call.call_id,
                connection.resource_ref,
                exc_info=True,
            )
            return None
        # The call ran on a hold: what billing held is what it charges.
        logger.error(
            "Tool call %s on %s could not be metered; its hold is captured at the estimate",
            call.call_id,
            connection.resource_ref,
            exc_info=True,
        )
        cost = before.cost
    if cost is None:
        return None
    settle_params = {"settle_params": cost.settle_params} if cost.settle_params else {}
    vendor_settles = cost.source is CostSourceKind.SETTLED
    if before.hold is not None:
        return _usage(
            call,
            line_key=call.call_id,
            payer=connection.payer,
            cost=cost,
            amount=to_money(before.hold.amount),
            currency=str(before.hold.currency),
            connection=connection,
            estimate=True,
            evidence={
                "hold_id": str(before.hold.hold_id),
                "settle": SETTLE_VENDOR if vendor_settles else SETTLE_CAPTURE,
                **settle_params,
            },
        )
    converted = (
        before.converted
        if before.converted is not None
        and before.cost is not None
        and (before.cost.vendor_cost, before.cost.currency) == (cost.vendor_cost, cost.currency)
        else await convert_cost(connection.payer, connection.connector, connection.tool, cost)
    )
    settle = SETTLE_VENDOR if vendor_settles else SETTLE_CONVERT if converted.pending else None
    evidence: dict[str, Any] = {"settle": settle, **settle_params} if settle else {}
    if settle == SETTLE_CONVERT:
        evidence["vendor_exact"] = cost.exact
    return _usage(
        call,
        line_key=call.call_id,
        payer=connection.payer,
        cost=cost,
        amount=converted.amount,
        currency=converted.currency,
        connection=connection,
        estimate=not cost.exact or settle is not None,
        evidence=evidence,
    )


async def _meter(
    call: GovernedToolCall, outcome: ToolCallOutcome, before: _Before
) -> list[ToolUsage]:
    usages: list[ToolUsage] = []
    connection = call.connection
    if connection is not None and outcome.success:
        line = await _connection_line(call, connection, outcome, before)
        if line is not None:
            usages.append(line)
    for payment in outcome.payments:
        if not payment.get("success"):
            continue
        cost = MeteredCost(
            Decimal(1),
            "payment",
            to_money(payment.get("amount_usd")),
            WALLET_CURRENCY,
            CostSourceKind.REPORTED,
        )
        connector = connection.connector if connection else ""
        tool = connection.tool if connection else call.authorization.tool_name
        converted = await convert_cost(Payer.PER_CALL, connector, tool, cost)
        evidence = {key: payment[key] for key in _PAYMENT_EVIDENCE_KEYS if payment.get(key)}
        if converted.pending:
            evidence.update(settle=SETTLE_CONVERT, vendor_exact=True)
        usages.append(
            _usage(
                call,
                line_key=f"{call.call_id}:payment:{payment.get('idempotency_key')}",
                payer=Payer.PER_CALL,
                cost=cost,
                amount=converted.amount,
                currency=converted.currency,
                connection=connection,
                estimate=converted.pending,
                evidence=evidence,
            )
        )
    return usages


async def _void(billing: tool_billing.ToolBilling | None, hold: Any, why: str) -> None:
    """Release a hold whose call did not use it; a failure leaves it to its TTL."""
    if billing is None or hold is None:
        return
    try:
        await tool_billing.billing_call("void", billing.void(hold_id=str(hold.hold_id)))
    except Exception:
        logger.error(
            "Hold %s (%s) could not be voided; it expires", hold.hold_id, why, exc_info=True
        )


async def _before(
    call: GovernedToolCall,
) -> tuple[_Before, tool_billing.ToolBilling | None, ToolAuthorizationDecision | None]:
    """The call's cost before it runs and, on the platform's key, its hold — or a refusal."""
    connection = call.connection
    if connection is None:
        return _Before(), None, None
    model = connection.cost_model
    try:
        cost = pre_call_cost(model, args=dict(call.authorization.tool_args))
    except ToolCostError as error:
        return _Before(), None, _denied(f"the cost of this call cannot be known: {error}")
    if connection.payer is not Payer.PLATFORM or model.source is CostSourceKind.FREE:
        if cost is None:
            return _Before(), None, None
        converted = await convert_cost(
            connection.payer, connection.connector, connection.tool, cost
        )
        return _Before(cost, converted), None, None
    if model.source is CostSourceKind.UNKNOWN:
        return (
            _Before(),
            None,
            _denied(
                f"{connection.resource_ref} runs on the platform's key but its connector "
                "declares no cost"
            ),
        )
    billing, failure = _billing()
    if failure is not None:
        return _Before(), None, _denied(f"tool billing is installed but failed to load: {failure}")
    if billing is None:
        converted = (
            await convert_cost(connection.payer, connection.connector, connection.tool, cost)
            if cost is not None
            else None
        )
        return _Before(cost, converted), None, None
    if cost is None:
        return (
            _Before(),
            None,
            _denied(
                f"{connection.resource_ref} runs on the platform's key but declares neither a "
                "rate nor an estimate to hold"
            ),
        )
    try:
        hold = await tool_billing.billing_call(
            "authorize",
            billing.authorize(
                workspace_id=str(call.authorization.workspace_id or ""),
                connector=connection.connector,
                tool=connection.tool,
                vendor_cost=cost.vendor_cost,
                vendor_currency=cost.currency,
                quantity=cost.quantity,
                unit=cost.unit,
                idempotency_key=f"hold:{call.call_id}:{uuid4().hex}",
            ),
        )
    except Exception:
        logger.error(
            "Billing could not authorize %s for call %s",
            connection.resource_ref,
            call.call_id,
            exc_info=True,
        )
        return _Before(), None, _denied("billing_unavailable: billing is temporarily unavailable")
    if not hold.allowed:
        return _Before(), None, _denied(f"{hold.code}: {hold.reason}")
    return (
        _Before(cost, Converted(to_money(hold.amount), str(hold.currency)), hold),
        billing,
        None,
    )


async def run_tool_call(
    call: GovernedToolCall,
    invoke: Callable[[], Awaitable[ToolCallOutcome]],
    *,
    audit: AuditHook,
    ledger: UsageLedger,
    spend_gate: SpendGate,
) -> ToolCallResult:
    decision = await authorize_tool_invocation(call.authorization)
    if decision.action is ToolAuthorizationAction.DENY:
        await audit(decision)
        return ToolCallResult(Verdict.DENIED, decision)
    if decision.action is ToolAuthorizationAction.REQUIRE_APPROVAL:
        if not call.approval_granted:
            return ToolCallResult(Verdict.HELD, decision)
        decision = ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, "approved")

    before, billing, refusal = await _before(call)
    if refusal is None:
        pending = (before.converted.amount, before.converted.currency) if before.converted else None
        reason = await spend_gate(call, pending)
        refusal = _denied(reason) if reason else None
        if refusal is not None:
            await _void(billing, before.hold, "refused by a spend cap")
    if refusal is not None:
        await audit(refusal)
        return ToolCallResult(Verdict.DENIED, refusal)

    await audit(decision)
    try:
        outcome = await invoke()
    except BaseException:
        await _void(billing, before.hold, "the call raised")
        raise
    if not outcome.success:
        await _void(billing, before.hold, "the call failed")
    usages = await _meter(call, outcome, before)
    metered = True
    replayed = outcome.replayed
    if usages:
        try:
            inserted = await ledger(usages)
            replayed = replayed or (inserted is not None and inserted < len(usages))
        except Exception:
            # The vendor answered and may have been paid; failing the call now would
            # lose the answer without un-spending the money. Logged with the keys
            # that replay it; an uncaptured hold expires.
            metered = False
            logger.exception(
                "Tool call %s ran but its cost lines were not recorded (%s)",
                call.call_id,
                [(u.line_key, u.vendor_cost, u.vendor_currency, u.evidence) for u in usages],
            )
        if replayed and outcome.success:
            # An earlier attempt's line, with its own hold, is the one captured.
            await _void(billing, before.hold, "the call's line was already recorded")
    return ToolCallResult(
        Verdict.RAN,
        decision,
        outcome,
        tuple(usages),
        metered,
        replayed,
        tool_billing.deployment_currency(),
    )
