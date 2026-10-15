"""A model call is refused once a monthly spend cap it falls under is reached.

The caps are the workspace's, its agent's and those on LLM spend. Read right before
every model call is held, whatever its surface (a run's turn or compaction, a direct
run, a trigger condition, a media call), so a cap reached while a run is going stops
its next call: the overshoot is the calls already in flight.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_governance.application import GovernancePolicyResolver
from agentarea_governance.domain.policies import BudgetPolicy

from .infrastructure.cost_repository import CostEntryRepository
from .spend_gate import monthly_llm_cap_reached

SPEND_CAP_REACHED = "spend_cap_reached"


class SpendCapReachedError(Exception):
    """A monthly spend cap is reached, so the model call is not made."""

    code = SPEND_CAP_REACHED

    def __init__(self, reason: str):
        super().__init__(f"{SPEND_CAP_REACHED}: {reason}")
        self.reason = reason


def caps_monthly_spend(budget: BudgetPolicy | None) -> bool:
    """Whether the budget has a monthly cap a model call falls under, so the ledger is read."""
    if budget is None:
        return False
    return (
        budget.monthly_spend_cap_usd is not None
        or budget.agent_monthly_spend_cap_usd is not None
        or any(cap.category == "llm" and cap.period != "run" for cap in budget.spend_caps or [])
    )


async def refuse_model_call_at_spend_cap(
    session: Any,
    user_context: UserContext,
    budget: BudgetPolicy | None,
    agent_id: UUID | None,
    *,
    now: datetime | None = None,
) -> None:
    """Raise ``SpendCapReachedError`` when a monthly cap the call falls under is reached.

    The workspace cap counts every line of the workspace this month; the agent cap,
    and an LLM cap bound to an agent, count ``agent_id``'s, as the check at the start
    of a run does.
    """
    if budget is None or not caps_monthly_spend(budget):
        return
    now = now or datetime.now(UTC)
    since = datetime(now.year, now.month, 1, tzinfo=UTC)
    ledger = CostEntryRepository(session, user_context)
    currency = get_customer_pricing().currency()
    if budget.monthly_spend_cap_usd is not None:
        spent = await ledger.sum_since(since, currency=currency)
        if spent >= budget.monthly_spend_cap_usd:
            raise SpendCapReachedError(
                f"Workspace monthly spend cap reached "
                f"({spent} {currency}/{budget.monthly_spend_cap_usd} {currency})"
            )
    if budget.agent_monthly_spend_cap_usd is not None and agent_id is not None:
        spent = await ledger.sum_since(since, currency=currency, agent_id=agent_id)
        if spent >= budget.agent_monthly_spend_cap_usd:
            raise SpendCapReachedError(
                f"Agent monthly spend cap reached "
                f"({spent} {currency}/{budget.agent_monthly_spend_cap_usd} {currency})"
            )
    reached = await monthly_llm_cap_reached(ledger, budget, agent_id, currency, now=now)
    if reached is None:
        return
    scope = "Agent" if reached.agent_id else "Workspace"
    raise SpendCapReachedError(
        f"{scope} monthly LLM spend cap reached "
        f"({reached.spent} {reached.currency}/{reached.cap} {reached.currency})"
    )


async def refuse_workspace_model_call_at_spend_cap(
    session: Any, user_context: UserContext, agent_id: UUID | None
) -> None:
    """The same refusal for a call outside a run, such as a trigger condition.

    Its caps are those of the policy the workspace and ``agent_id`` resolve to.
    """
    policy = await GovernancePolicyResolver(RepositoryFactory(session, user_context)).resolve(
        workspace_id=str(user_context.workspace_id),
        agent_id=agent_id,
        user_id=user_context.user_id,
    )
    await refuse_model_call_at_spend_cap(session, user_context, policy.budget, agent_id)
