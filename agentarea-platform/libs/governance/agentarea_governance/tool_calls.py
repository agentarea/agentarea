"""The one layer every tool call passes, from a run's tool activity or from /mcp.

In order (wiki ADR-0038):

1. The policy verdict: the runtime PDP (``authorize_tool_invocation``), the same
   answer disclosure and the workflow gate read. A held call returns to its caller,
   whose transport asks a person (a run's escalation, an /mcp approval link) and
   calls again once it is approved.
2. The spend gate: the caller's caps over the spend ledger (agent, workspace,
   client, connection, tool).
3. For a call on the platform's key, the balance gate: the installed
   ``entitlement_guard``, asked about the call's vendor cost metric and connector.
   Without one installed the call is governed by policy and caps alone; one that is
   installed but failed to load refuses.
4. The call.
5. The meter: one line per known cost, through the caller's ``ledger``, keyed on the
   tool call so a retry writes it once. The connector's declared cost for a call
   that succeeded, and every wallet payment (x402/MPP) the call settled.

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
from functools import cache
from typing import Any
from uuid import UUID

from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationDecision,
    ToolAuthorizationRequest,
    authorize_tool_invocation,
)
from agentarea_common.extensions import customer_pricing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.money import ZERO, to_money
from agentarea_common.tool_cost import (
    CostSourceKind,
    MeteredCost,
    Payer,
    ToolConnection,
    ToolCostError,
    meter,
)

from .domain.enums import InterceptorAction, Phase
from .domain.models import InterceptorContext

logger = logging.getLogger(__name__)

ENTITLEMENT_GUARD_EXTENSION = "entitlement_guard"
VENDOR_COST_METRIC = "tool.vendor_cost"
WALLET_CURRENCY = "USD"
_BILLABLE_ON_PLATFORM = frozenset(
    {CostSourceKind.FREE, CostSourceKind.RATE, CostSourceKind.REPORTED}
)
_PAYMENT_EVIDENCE_KEYS = ("protocol", "recipient", "tx_hash")


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
    """One metered line: what a call cost, whom, and the amount caps count."""

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

    @property
    def cost(self) -> Decimal:
        """The run-budget amount of the call: every line but wallet payments."""
        return sum((u.amount for u in self.usages if u.payer is not Payer.PER_CALL), ZERO)


AuditHook = Callable[[ToolAuthorizationDecision], Awaitable[None]]
# Returns how many lines it inserted (a line already stored is not), or None if unknown.
UsageLedger = Callable[[list[ToolUsage]], Awaitable[int | None]]
SpendGate = Callable[[GovernedToolCall], Awaitable[str | None]]


@cache
def entitlement_guard() -> Any | None:
    """The installed entitlement gate, built once per process like the pipeline's."""
    factory = ExtensionRegistry.get_factory(ENTITLEMENT_GUARD_EXTENSION)
    return factory() if factory is not None else None


def _denied(reason: str) -> ToolAuthorizationDecision:
    return ToolAuthorizationDecision(ToolAuthorizationAction.DENY, reason)


async def _balance_gate(
    call: GovernedToolCall, connection: ToolConnection
) -> ToolAuthorizationDecision | None:
    """A refusal by the balance gate, or None when the call may spend the platform's key."""
    guard = entitlement_guard()
    if guard is None:
        failure = ExtensionRegistry.get_failure(ENTITLEMENT_GUARD_EXTENSION)
        if failure is not None:
            return _denied(f"the entitlement gate is installed but failed to load: {failure}")
        return None
    request = call.authorization
    verdict = await guard.execute(
        InterceptorContext(
            agent_id=call.agent_id,
            workspace_id=str(request.workspace_id or ""),
            user_id=str(request.user_id or ""),
            phase=Phase.PRE_TOOL_CALL,
            action_type="tool_call",
            action_name=request.tool_name,
            action_params=dict(request.tool_args),
            execution_state={
                "paid_call": {
                    "payer": Payer.PLATFORM.value,
                    "metric_type": f"{VENDOR_COST_METRIC}.{connection.cost_model.currency}",
                    "resource_ref": connection.resource_ref,
                }
            },
        )
    )
    if verdict.action is InterceptorAction.DENY:
        return _denied(f"{verdict.interceptor_name}: {verdict.reason}")
    return None


async def _amount(
    payer: Payer, connector: str, tool: str, vendor_cost: Decimal, currency: str
) -> tuple[Decimal, str]:
    """The line's amount and currency: converted where a billing extension prices it.

    An installed pricing that cannot convert the currency is a misconfiguration worth
    a warning; the line keeps the vendor's currency and caps in that currency count it.
    """
    try:
        return await customer_pricing.price_vendor_cost(
            payer=payer.value,
            connector=connector,
            tool=tool,
            vendor_cost=vendor_cost,
            currency=currency,
        )
    except customer_pricing.FxUnavailableError:
        logger.warning("Tool cost kept in %s for %s#%s", currency, connector, tool, exc_info=True)
        return vendor_cost, currency


def _usage(
    call: GovernedToolCall,
    *,
    line_key: str,
    payer: Payer,
    cost: MeteredCost,
    amount: Decimal,
    currency: str,
    connection: ToolConnection | None,
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
        evidence=evidence,
    )


async def _meter(call: GovernedToolCall, outcome: ToolCallOutcome) -> list[ToolUsage]:
    usages: list[ToolUsage] = []
    connection = call.connection
    if connection is not None and outcome.success:
        try:
            cost = meter(
                connection.cost_model,
                args=dict(call.authorization.tool_args),
                body=outcome.body,
                meta=outcome.meta,
            )
        except ToolCostError:
            logger.error(
                "Tool call %s on %s could not be metered; no line recorded",
                call.call_id,
                connection.resource_ref,
                exc_info=True,
            )
            cost = None
        if cost is not None:
            amount, currency = await _amount(
                connection.payer,
                connection.connector,
                connection.tool,
                cost.vendor_cost,
                cost.currency,
            )
            usages.append(
                _usage(
                    call,
                    line_key=call.call_id,
                    payer=connection.payer,
                    cost=cost,
                    amount=amount,
                    currency=currency,
                    connection=connection,
                    evidence={},
                )
            )
    for payment in outcome.payments:
        if not payment.get("success"):
            continue
        vendor_cost = to_money(payment.get("amount_usd"))
        cost = MeteredCost(
            Decimal(1), "payment", vendor_cost, WALLET_CURRENCY, CostSourceKind.REPORTED
        )
        amount, currency = await _amount(
            Payer.PER_CALL,
            connection.connector if connection else "",
            connection.tool if connection else call.authorization.tool_name,
            vendor_cost,
            WALLET_CURRENCY,
        )
        usages.append(
            _usage(
                call,
                line_key=f"{call.call_id}:payment:{payment.get('idempotency_key')}",
                payer=Payer.PER_CALL,
                cost=cost,
                amount=amount,
                currency=currency,
                connection=connection,
                evidence={key: payment[key] for key in _PAYMENT_EVIDENCE_KEYS if payment.get(key)},
            )
        )
    return usages


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

    connection = call.connection
    refusal: ToolAuthorizationDecision | None = None
    if (
        connection is not None
        and connection.payer is Payer.PLATFORM
        and connection.cost_model.source not in _BILLABLE_ON_PLATFORM
    ):
        refusal = _denied(
            f"{connection.resource_ref} runs on the platform's key but its connector "
            f"declares no rate or reported cost ({connection.cost_model.source.value})"
        )
    if refusal is None:
        reason = await spend_gate(call)
        refusal = _denied(reason) if reason else None
    if (
        refusal is None
        and connection is not None
        and connection.payer is Payer.PLATFORM
        and connection.cost_model.source is not CostSourceKind.FREE
    ):
        refusal = await _balance_gate(call, connection)
    if refusal is not None:
        await audit(refusal)
        return ToolCallResult(Verdict.DENIED, refusal)

    await audit(decision)
    outcome = await invoke()
    usages = await _meter(call, outcome)
    metered = True
    replayed = outcome.replayed
    if usages:
        try:
            inserted = await ledger(usages)
            replayed = replayed or (inserted is not None and inserted < len(usages))
        except Exception:
            # The vendor answered and may have been paid; failing the call now would
            # lose the answer without un-spending the money. Logged with the keys
            # that replay it.
            metered = False
            logger.exception(
                "Tool call %s ran but its cost lines were not recorded (%s)",
                call.call_id,
                [(u.line_key, u.vendor_cost, u.vendor_currency) for u in usages],
            )
    return ToolCallResult(Verdict.RAN, decision, outcome, tuple(usages), metered, replayed)
