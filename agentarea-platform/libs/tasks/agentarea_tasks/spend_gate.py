"""The spend gate of the tool-call layer: the caller's monthly caps over the ledger.

Every cap the call falls under is summed from its current lines this calendar month
(UTC): the workspace cap, the calling agent's cap, and every cap narrowed to the
call's client, connection, tool or currency. A cap counts only lines in its own
currency (the billing currency unless it declares another); nothing is converted, so
spend in another currency is not covered by it. A cap already reached refuses the
call before the vendor is asked.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from agentarea_common.extensions import customer_pricing
from agentarea_governance.domain.policies import effective_policy_from_json
from agentarea_governance.tool_calls import GovernedToolCall

from .infrastructure.cost_repository import CostEntryRepository, SpendScope


@dataclass(frozen=True)
class _Cap:
    label: str
    amount: Decimal
    currency: str
    scope: SpendScope


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
            else "agent monthly"
            if cap.own_agent
            else "workspace monthly"
        )
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
                ),
            )
        )
    return caps


async def spend_cap_refusal(
    repo: CostEntryRepository, call: GovernedToolCall, *, now: datetime | None = None
) -> str | None:
    """Why the call may not spend more, or None when no cap it falls under is reached."""
    caps = _caps(call, customer_pricing.get_customer_pricing().currency())
    since = _month_start(now or datetime.now(UTC))
    for cap in caps:
        spent = await repo.sum_since(since, currency=cap.currency, scope=cap.scope)
        if spent >= cap.amount:
            return (
                f"{cap.label} spend cap of {cap.amount.normalize():f} {cap.currency} reached: "
                f"{spent.normalize():f} {cap.currency} spent this month"
            )
    return None


def workspace_cap_currencies(caps: list[dict], billing_currency: str) -> set[str]:
    """The currencies the workspace-wide monthly spend caps count, from their params.

    A cap counts its declared currency, or the billing currency when it declares none.
    Caps narrowed to a client, connection or tool, and per-run caps, are not workspace
    caps.
    """
    return {
        str(params.get("currency") or billing_currency)
        for params in caps
        if params.get("period", "month") == "month"
        and not any(params.get(key) for key in ("client_id", "connection_id", "tool"))
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
