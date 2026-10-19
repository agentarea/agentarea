"""The spend gate of the tool-call layer: the caller's caps over the ledger.

Every cap the call falls under is summed from its current lines this calendar month
(UTC): the workspace cap, the calling agent's cap, and every cap narrowed to tool
spend or to the call's client, connection, tool or currency. A per-run cap narrowed
to tool spend, a connection or a tool sums the run's own lines instead. A cap on LLM
spend never refuses a tool call. A cap counts only lines in its own currency (the
deployment currency unless it declares another); nothing is converted, so spend in
another currency is not covered by it. A cap already reached, or one that the call's
known cost would take past its amount, refuses the call before the vendor is asked.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from agentarea_common.extensions import tool_billing
from agentarea_governance.domain.policies import BudgetPolicy, effective_policy_from_json
from agentarea_governance.tool_calls import GovernedToolCall, PendingCost

from .domain.costs import CostCategory
from .infrastructure.cost_repository import CostEntryRepository, SpendScope

_EVER = datetime(1970, 1, 1, tzinfo=UTC)
_MONTHLY_LABELS = {
    None: "workspace monthly",
    "agent": "agent monthly",
    "tools": "monthly tools",
}


@dataclass(frozen=True)
class _Cap:
    label: str
    amount: Decimal
    currency: str
    scope: SpendScope
    per_run: bool = False


def _month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def _caps(call: GovernedToolCall, budget: BudgetPolicy | None, billing_currency: str) -> list[_Cap]:
    if budget is None:
        return []
    caps: list[_Cap] = []
    if budget.monthly_spend_cap_usd is not None:
        caps.append(
            _Cap("workspace monthly", budget.monthly_spend_cap_usd, billing_currency, SpendScope())
        )
    if budget.run_budget_usd is not None and call.task_id is not None:
        # The run's budget counts every line of the run; checked here too, so a call
        # whose known cost would take the run past it is refused before it runs.
        caps.append(
            _Cap(
                "run",
                budget.run_budget_usd,
                billing_currency,
                SpendScope(task_id=UUID(call.task_id)),
                per_run=True,
            )
        )
    if budget.agent_monthly_spend_cap_usd is not None and call.agent_id is not None:
        caps.append(
            _Cap(
                "agent monthly",
                budget.agent_monthly_spend_cap_usd,
                billing_currency,
                SpendScope(agent_id=call.agent_id),
            )
        )
    connection = call.connection
    for cap in budget.spend_caps or []:
        if cap.category == "llm":
            continue
        if cap.category == "tools" and connection is None and not cap.tool:
            continue
        per_run = cap.period == "run"
        if per_run and call.task_id is None:
            continue
        if cap.client_id and cap.client_id != call.client_id:
            continue
        if cap.connection_id and (
            connection is None or cap.connection_id != connection.connection_id
        ):
            continue
        if cap.tool and (connection is None or cap.tool != connection.tool):
            continue
        if cap.own_agent and call.agent_id is None:
            continue
        narrowed = (
            "tool"
            if cap.tool
            else "connection"
            if cap.connection_id
            else "client"
            if cap.client_id
            else "tools"
            if cap.category == "tools"
            else "agent"
            if cap.own_agent
            else None
        )
        if per_run:
            label = f"run {narrowed}" if narrowed else "run"
        else:
            label = _MONTHLY_LABELS.get(narrowed) or str(narrowed)
        caps.append(
            _Cap(
                label,
                cap.amount_usd,
                cap.currency or billing_currency,
                SpendScope(
                    agent_id=call.agent_id if cap.own_agent else None,
                    client_id=UUID(cap.client_id) if cap.client_id else None,
                    connection_id=cap.connection_id,
                    tool=cap.tool,
                    task_id=UUID(call.task_id) if per_run and call.task_id else None,
                    category=CostCategory.SERVICE if cap.category == "tools" else None,
                ),
                per_run,
            )
        )
    return caps


async def spend_cap_refusal(
    repo: CostEntryRepository,
    call: GovernedToolCall,
    pending: PendingCost | None = None,
    *,
    budget: BudgetPolicy | None = None,
    now: datetime | None = None,
) -> str | None:
    """Why the call may not spend more, or None when every cap it falls under allows it.

    ``budget`` holds the caps; a run passes its monthly caps as they are now (see
    ``model_spend_caps.current_budget``), not as its policy froze them. Without it
    the caps are those of the call's policy. ``pending`` is what the call will cost,
    when that is known before it runs; it counts against the caps in its currency.
    """
    if budget is None:
        budget = effective_policy_from_json(call.authorization.effective_policy).budget
    caps = _caps(call, budget, tool_billing.deployment_currency())
    month_start = _month_start(now or datetime.now(UTC))
    for cap in caps:
        since = _EVER if cap.per_run else month_start
        spent = await repo.sum_since(since, currency=cap.currency, scope=cap.scope)
        period = "in this run" if cap.per_run else "this month"
        if spent >= cap.amount:
            return (
                f"{cap.label} spend cap of {cap.amount.normalize():f} {cap.currency} reached: "
                f"{spent.normalize():f} {cap.currency} spent {period}"
            )
        if pending is not None and pending[1] == cap.currency and spent + pending[0] > cap.amount:
            return (
                f"{cap.label} spend cap of {cap.amount.normalize():f} {cap.currency} would be "
                f"exceeded: {spent.normalize():f} {cap.currency} spent {period}, this call "
                f"costs {pending[0].normalize():f} {cap.currency}"
            )
    return None


@dataclass(frozen=True)
class LlmCapReached:
    """A monthly LLM spend cap that is reached; ``agent_id`` when it is the agent's own."""

    spent: Decimal
    cap: Decimal
    currency: str
    agent_id: UUID | None


async def monthly_llm_cap_reached(
    repo: CostEntryRepository,
    budget: BudgetPolicy | None,
    agent_id: UUID | None,
    billing_currency: str,
    *,
    now: datetime | None = None,
) -> LlmCapReached | None:
    """The first monthly cap on LLM spend that this month's model lines reached.

    Checked where a run is submitted and where it starts or resumes, as the workspace
    cap is. A cap bound to an agent counts that agent's lines and needs ``agent_id``.
    """
    since = _month_start(now or datetime.now(UTC))
    for cap in (budget.spend_caps or []) if budget else []:
        if cap.category != "llm" or cap.period == "run":
            continue
        if cap.own_agent and agent_id is None:
            continue
        currency = cap.currency or billing_currency
        scope = SpendScope(
            agent_id=agent_id if cap.own_agent else None, category=CostCategory.MODEL
        )
        spent = await repo.sum_since(since, currency=currency, scope=scope)
        if spent >= cap.amount_usd:
            return LlmCapReached(spent, cap.amount_usd, currency, scope.agent_id)
    return None


def workspace_cap_currencies(caps: list[dict], billing_currency: str) -> set[str]:
    """The currencies the workspace-wide monthly spend caps count, from their params.

    A cap counts its declared currency, or the billing currency when it declares none.
    Caps narrowed to LLM or tool spend, a client, connection or tool, and per-run caps,
    are not workspace caps.
    """
    return {
        str(params.get("currency") or billing_currency)
        for params in caps
        if params.get("period", "month") == "month"
        and not any(params.get(key) for key in ("category", "client_id", "connection_id", "tool"))
    }


def spend_not_covered(
    spend_by_currency: dict[str | None, Decimal], cap_currencies: set[str]
) -> dict[str, Decimal]:
    """Spend in currencies no cap counts: shown, never converted, never blocked.

    Without any cap there is nothing to be covered by, so nothing is reported. A
    ``None`` currency is the billing currency of backfilled lines, which caps count.
    """
    if not cap_currencies:
        return {}
    return {
        currency: amount
        for currency, amount in sorted(spend_by_currency.items(), key=lambda item: str(item[0]))
        if currency is not None and currency not in cap_currencies and amount > 0
    }
