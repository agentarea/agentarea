"""The spend gate of the tool-call layer: the caller's caps over the ledger.

Every cap the call falls under is summed from its current lines this calendar month
(UTC): the workspace cap, the calling agent's cap, and every cap narrowed to tool
spend or to the call's client, connection, tool or currency. A per-run cap narrowed
to tool spend, a connection or a tool sums the run's own lines instead. A cap on LLM
spend never refuses a tool call. A cap counts only lines in its own currency (the
billing currency unless it declares another); nothing is converted, so spend in
another currency is not covered by it. A cap already reached refuses the call before
the vendor is asked.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from agentarea_common.extensions import customer_pricing
from agentarea_governance.domain.policies import BudgetPolicy, effective_policy_from_json
from agentarea_governance.tool_calls import GovernedToolCall

from .domain.costs import CostCategory
from .infrastructure.cost_repository import CostEntryRepository, SpendScope

_EVER = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class _Cap:
    label: str
    amount: Decimal
    currency: str
    scope: SpendScope
    per_run: bool = False


def _month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1, tzinfo=UTC)


def _caps(call: GovernedToolCall, billing_currency: str) -> list[_Cap]:
    budget = effective_policy_from_json(call.authorization.effective_policy).budget
    if budget is None:
        return []
    caps: list[_Cap] = []
    if budget.monthly_spend_cap_usd is not None:
        caps.append(
            _Cap("workspace monthly", budget.monthly_spend_cap_usd, billing_currency, SpendScope())
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
        label = (
            "tool"
            if cap.tool
            else "connection"
            if cap.connection_id
            else "client"
            if cap.client_id
            else "tools"
            if cap.category == "tools"
            else "agent monthly"
            if cap.own_agent
            else "workspace monthly"
        )
        if per_run:
            label = f"run {label}"
        elif cap.category == "tools" and not (cap.client_id or cap.connection_id):
            label = f"monthly {label}"
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
    repo: CostEntryRepository, call: GovernedToolCall, *, now: datetime | None = None
) -> str | None:
    """Why the call may not spend more, or None when no cap it falls under is reached."""
    caps = _caps(call, customer_pricing.get_customer_pricing().currency())
    month_start = _month_start(now or datetime.now(UTC))
    for cap in caps:
        since = _EVER if cap.per_run else month_start
        spent = await repo.sum_since(since, currency=cap.currency, scope=cap.scope)
        if spent >= cap.amount:
            return (
                f"{cap.label} spend cap of {cap.amount.normalize():f} {cap.currency} reached: "
                f"{spent.normalize():f} {cap.currency} spent "
                f"{'in this run' if cap.per_run else 'this month'}"
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
