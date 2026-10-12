"""The one layer every tool call passes, from a run's tool activity or from /mcp.

In order:

1. The policy verdict — the runtime PDP (``authorize_tool_invocation``), the same
   answer disclosure and the workflow gate read. A held call returns to its caller,
   whose transport asks a person (a run's escalation, an /mcp approval link) and
   calls again once it is approved.
2. For a call on a platform-funded connection, its price (``customer_pricing``; a
   tool with none is refused) and the entitlement gate: the installed
   ``entitlement_guard``, the same one that gates a platform-funded model call,
   asked about the tool's metric and resource. Fails closed.
3. The call.
4. For a platform-funded call that ran, one line in the spend ledger through the
   caller's ``ledger``, keyed on the tool call id so a retry writes it once. Its
   amount is the price estimate for caps and display; billing rates the usage itself.

Each path keeps its own audit trail and passes it in; the layer reports every verdict
it reaches, including a refusal by the price or the entitlement gate.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from agentarea_common.constants import MANAGED_BY_PLATFORM
from agentarea_common.extensions import customer_pricing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.money import Money

from .domain.enums import InterceptorAction, Phase
from .domain.models import InterceptorContext

logger = logging.getLogger(__name__)

ENTITLEMENT_GUARD_EXTENSION = "entitlement_guard"


@dataclass(frozen=True)
class PlatformFundedTool:
    """What a call on a platform-funded connection uses, as the tool declares it."""

    resource_ref: str


@dataclass(frozen=True)
class GovernedToolCall:
    authorization: ToolAuthorizationRequest
    call_id: str
    agent_id: UUID | None
    task_id: str | None
    client_id: str | None = None
    platform_funded: PlatformFundedTool | None = None
    approval_granted: bool = False


@dataclass(frozen=True)
class ToolCallOutcome:
    success: bool
    usage_quantity: int | None = None
    value: Any = None


@dataclass(frozen=True)
class PlatformToolUsage:
    """One platform-funded call that ran: what it used, and the customer's price for it."""

    call_id: str
    workspace_id: str
    user_id: str
    agent_id: UUID | None
    task_id: str | None
    client_id: str | None
    tool_name: str
    resource_ref: str
    quantity: int
    amount: Money
    currency: str
    occurred_at: datetime


class Verdict(StrEnum):
    RAN = "ran"
    DENIED = "denied"
    HELD = "held"


@dataclass(frozen=True)
class ToolCallResult:
    verdict: Verdict
    decision: ToolAuthorizationDecision
    outcome: ToolCallOutcome | None = None
    usage: PlatformToolUsage | None = None


AuditHook = Callable[[ToolAuthorizationDecision], Awaitable[None]]
UsageLedger = Callable[[PlatformToolUsage], Awaitable[None]]


@cache
def entitlement_guard() -> Any | None:
    """The installed entitlement gate, built once per process like the pipeline's."""
    factory = ExtensionRegistry.get_factory(ENTITLEMENT_GUARD_EXTENSION)
    return factory() if factory is not None else None


def _denied(reason: str) -> ToolAuthorizationDecision:
    return ToolAuthorizationDecision(ToolAuthorizationAction.DENY, reason)


async def _gate(call: GovernedToolCall, paid: PlatformFundedTool) -> ToolAuthorizationDecision:
    guard = entitlement_guard()
    if guard is None:
        return _denied("no entitlement gate is installed to charge a platform-funded tool call")
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
                "paid_call": {"resource_ref": paid.resource_ref, "managed_by": MANAGED_BY_PLATFORM}
            },
        )
    )
    if verdict.action is InterceptorAction.DENY:
        return _denied(f"{verdict.interceptor_name}: {verdict.reason}")
    return ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, verdict.reason)


async def _record(
    call: GovernedToolCall,
    paid: PlatformFundedTool,
    price: Money,
    currency: str,
    outcome: ToolCallOutcome,
    ledger: UsageLedger,
) -> PlatformToolUsage | None:
    if not outcome.success:
        return None
    quantity = outcome.usage_quantity
    if not quantity or quantity <= 0:
        # The connection's contract is to report usage for every call that ran;
        # nothing here invents a quantity it did not report.
        logger.error(
            "Platform-funded tool %s reported no usage for call %s; nothing recorded",
            call.authorization.tool_name,
            call.call_id,
        )
        return None
    request = call.authorization
    usage = PlatformToolUsage(
        call_id=call.call_id,
        workspace_id=str(request.workspace_id or ""),
        user_id=str(request.user_id or ""),
        agent_id=call.agent_id,
        task_id=call.task_id,
        client_id=call.client_id,
        tool_name=request.tool_name,
        resource_ref=paid.resource_ref,
        quantity=quantity,
        amount=price * quantity,
        currency=currency,
        occurred_at=datetime.now(UTC),
    )
    try:
        await ledger(usage)
    except Exception:
        # The vendor was paid and answered; failing the call now would lose the
        # answer without un-spending the money. Logged with the key that replays it.
        logger.exception(
            "Platform-funded tool call %s ran but its usage was not recorded "
            "(resource=%s quantity=%s workspace=%s)",
            call.call_id,
            paid.resource_ref,
            quantity,
            request.workspace_id,
        )
    return usage


async def run_tool_call(
    call: GovernedToolCall,
    invoke: Callable[[], Awaitable[ToolCallOutcome]],
    *,
    audit: AuditHook,
    ledger: UsageLedger,
) -> ToolCallResult:
    decision = await authorize_tool_invocation(call.authorization)
    if decision.action is ToolAuthorizationAction.DENY:
        await audit(decision)
        return ToolCallResult(Verdict.DENIED, decision)
    if decision.action is ToolAuthorizationAction.REQUIRE_APPROVAL:
        if not call.approval_granted:
            return ToolCallResult(Verdict.HELD, decision)
        decision = ToolAuthorizationDecision(ToolAuthorizationAction.ALLOW, "approved")

    paid = call.platform_funded
    if paid is None:
        await audit(decision)
        return ToolCallResult(Verdict.RAN, decision, await invoke())

    if not paid.resource_ref:
        refused = _denied("this platform-managed tool declares no metered resource")
        await audit(refused)
        return ToolCallResult(Verdict.DENIED, refused)
    pricing = customer_pricing.get_customer_pricing()
    try:
        price = await customer_pricing.price_tool_call(paid.resource_ref, pricing=pricing)
    except customer_pricing.ToolCallUnpricedError as error:
        refused = _denied(f"this paid tool has no price: {error}")
        await audit(refused)
        return ToolCallResult(Verdict.DENIED, refused)
    gated = await _gate(call, paid)
    if not gated.allowed:
        await audit(gated)
        return ToolCallResult(Verdict.DENIED, gated)

    await audit(decision)
    outcome = await invoke()
    usage = await _record(call, paid, price, pricing.currency(), outcome, ledger)
    return ToolCallResult(Verdict.RAN, decision, outcome, usage)
