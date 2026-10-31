"""Workspace dashboard endpoint.

Single round-trip aggregate that powers the post-login `/dashboard` page:
spend (today / MTD / cap / projection, the top agents, runtime usage), org
blockers (HITL, runs waiting to continue, blocked and failed runs in the last
24h, exhausted wallets), what is broken (connections, triggers), running and
recently finished tasks, and the schedule for the weeks ahead (cron triggers
and tasks booked for a later moment).

All data is workspace-scoped via UserContext. Live computation against
existing `tasks` and `wallets` tables — no rollup tables in v1. Money fields
are `Money` (Decimal, serialized as a string), as in the wallet API.
"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1._schedule_preview import cron_runs, runs_per_day
from agentarea_common.auth import UserContextDep
from agentarea_common.auth.route_authz import requires_workspace_admin, unrestricted
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config.database import get_db_session
from agentarea_common.extensions.account_balance import get_account_balance_source
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_common.extensions.workspace_usage import get_workspace_usage_source
from agentarea_common.money import ZERO, Money, to_money
from agentarea_common.utils.types import UtcDatetime
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
    is_scoped_spend_cap,
)
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
from agentarea_tasks.domain.statuses import TASK_STATUSES, TaskStatus
from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository, SpendScope
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.spend_gate import spend_not_covered, workspace_cap_currencies
from agentarea_triggers.infrastructure.orm import TriggerORM
from agentarea_triggers.infrastructure.repository import TriggerRepository
from agentarea_wallet.infrastructure.repository import WalletRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

# Long enough for a month view: from any day to the end of the week after month end.
SCHEDULE_HORIZON_DAYS = 42
# A schedule firing more often than this per day is summarised, not listed.
MAX_LISTED_RUNS_PER_DAY = 3

# Where each stored status shows up on the dashboard. Keyed by the canonical
# vocabulary: a status added there fails this import instead of silently
# vanishing from every panel.
_DashboardPlace = Literal["active", "hitl", "continuation", "blocked", "finished", "schedule"]
_STATUS_PLACE: dict[TaskStatus, _DashboardPlace] = {
    "submitted": "active",
    "pending": "active",
    "preparing": "active",
    # Booked for a later moment; not work in flight yet.
    "scheduled": "schedule",
    "running": "active",
    "working": "active",
    "waiting_for_input": "hitl",
    "waiting_for_approval": "hitl",
    "waiting_for_continuation": "continuation",
    # Still the run's own: it retries by itself until the service answers.
    "waiting_for_infrastructure": "active",
    "blocked": "blocked",
    "completed": "finished",
    "failed": "finished",
    "cancelled": "finished",
}
if _STATUS_PLACE.keys() != TASK_STATUSES:
    raise RuntimeError("Dashboard status placement must cover every TaskStatus")


def _statuses(*places: _DashboardPlace) -> tuple[str, ...]:
    return tuple(status for status, place in _STATUS_PLACE.items() if place in places)


ACTIVE_TASK_STATUSES = _statuses("active")
HITL_TASK_STATUSES = _statuses("hitl")
CONTINUATION_TASK_STATUSES = _statuses("continuation")
BLOCKED_TASK_STATUSES = _statuses("blocked")
# A blocked run has ended too, so it is also listed among the finished ones.
FINISHED_TASK_STATUSES = _statuses("finished", "blocked")
SCHEDULED_TASK_STATUSES = _statuses("schedule")
TASK_LIST_LIMIT = 10
BLOCKER_LIST_LIMIT = 20
TOP_AGENTS_LIMIT = 3
HEALTH_LIST_LIMIT = 20
# Days of spend whose average pace carries the month to its end.
PROJECTION_WINDOW_DAYS = 7

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]


class CurrencySpend(BaseModel):
    currency: str
    amount: Money


class SpendCard(BaseModel):
    today_usd: Money
    mtd_usd: Money
    cap_usd: Money | None
    pct_of_cap: float | None
    # Month-to-date plus the rest of the month at the pace of the last full days.
    projected_eom_usd: Money | None
    projection_method: str = "trailing-7d"
    # Month-to-date spend in a currency no workspace monthly cap is in: never
    # converted, never blocked. Empty when the workspace has no such cap.
    not_covered: list[CurrencySpend] = Field(default_factory=list)
    # The part of ``mtd_usd`` that is an estimate (a public rate, a held amount not
    # captured yet, a cost the vendor has still to settle); the rest is exact.
    mtd_estimate_usd: Money = Decimal(0)


class HitlBlocker(BaseModel):
    task_id: UUID
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    # What the run waits for: an answer, an approval, or to be continued.
    status: str
    description: str
    created_at: UtcDatetime


class WalletExhaustedBlocker(BaseModel):
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    budget_usd: Money
    period: str


class FailedTaskBlocker(BaseModel):
    task_id: UUID
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    error: str | None
    occurred_at: UtcDatetime


class BlockedTaskBlocker(BaseModel):
    task_id: UUID
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    description: str
    error: str | None
    occurred_at: UtcDatetime


class Blockers(BaseModel):
    hitl: list[HitlBlocker]
    awaiting_continuation: list[HitlBlocker]
    blocked_24h: list[BlockedTaskBlocker]
    wallet_exhausted: list[WalletExhaustedBlocker]
    failed_24h: list[FailedTaskBlocker]


class DashboardTask(BaseModel):
    task_id: UUID
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    title: str
    status: str
    started_at: UtcDatetime | None
    finished_at: UtcDatetime | None
    # None when the task reported no cost, or one that is not an amount.
    cost_usd: Money | None


class ScheduledRun(BaseModel):
    """One upcoming run: a cron trigger firing or a task booked for later.

    Exactly one of `trigger_id` and `task_id` is set.
    """

    fires_at: UtcDatetime
    trigger_id: UUID | None = None
    task_id: UUID | None = None
    agent_id: UUID
    agent_name: str | None = None
    title: str


class FrequentSchedule(BaseModel):
    trigger_id: UUID
    agent_id: UUID
    agent_name: str | None = None
    title: str
    cron_expression: str
    runs_per_day: int
    next_run_at: UtcDatetime


class Schedule(BaseModel):
    horizon_days: int
    runs: list[ScheduledRun]
    frequent: list[FrequentSchedule]


class DailySpendPoint(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    usd: Money


class AgentSpend(BaseModel):
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    usd: Money


class RuntimeUsage(BaseModel):
    """What the workspace's runtime used this month; quantities, never a price."""

    cpu_core_hours: Decimal
    memory_gib_hours: Decimal
    # Stored now, not integrated over the month.
    storage_gib: Decimal


class BrokenConnection(BaseModel):
    instance_id: UUID
    name: str
    reason: Literal["verification_failed", "last_call_failed"]
    error: str | None
    at: str | None


class BrokenTrigger(BaseModel):
    trigger_id: UUID
    name: str
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
    # failing: its last runs failed in a row and it is still on; stopped_after_failures:
    # it turned itself off at its failure threshold; needs_owner: whoever set it up can
    # no longer run its agent.
    reason: Literal["failing", "stopped_after_failures", "needs_owner"]
    consecutive_failures: int
    failure_threshold: int
    last_execution_at: UtcDatetime | None


class Health(BaseModel):
    connections: list[BrokenConnection]
    triggers: list[BrokenTrigger]


class DashboardResponse(BaseModel):
    spend: SpendCard
    blockers: Blockers
    active_tasks: list[DashboardTask]
    recent_tasks: list[DashboardTask]
    schedule: Schedule
    daily_spend: list[DailySpendPoint]
    # The agents that spent the most this month, highest first.
    top_agents: list[AgentSpend]
    health: Health
    # None when this deployment meters no runtime.
    usage: RuntimeUsage | None


_MONEY = TypeAdapter(Money)
_CENT = Decimal("0.01")


def project_month_end(
    mtd_usd: Decimal, spend_by_day: Mapping[str, Decimal], now: datetime
) -> Decimal:
    """Month-to-date spend plus the rest of the month at the recent daily pace.

    The pace is the average of the last ``PROJECTION_WINDOW_DAYS`` full UTC days
    (``spend_by_day`` is keyed by ISO date), so the first days of a month are
    projected from last month's pace rather than from a day or two of this one.
    Today is still running, so its own spend sets no pace.
    """
    today = now.date()
    window = [today - timedelta(days=i) for i in range(1, PROJECTION_WINDOW_DAYS + 1)]
    pace = sum((spend_by_day.get(day.isoformat(), ZERO) for day in window), ZERO) / len(window)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    days_left = Decimal((next_month - now).total_seconds()) / Decimal(86400)
    return (mtd_usd + pace * days_left).quantize(_CENT)


def _is_monthly_spend_cap(rule: PolicyRule) -> bool:
    return (
        rule.effect == PolicyEffect.CAP
        and rule.target == "spend"
        and (rule.params or {}).get("period", "month") == "month"
        and not is_scoped_spend_cap(rule.params)
    )


def _task_cost(task: TaskORM) -> Decimal | None:
    cost = task.result.get("total_cost") if isinstance(task.result, dict) else None
    if cost is None:
        return None
    try:
        return _MONEY.validate_python(cost)
    except ValidationError:
        # One unreadable row must not take the whole dashboard down.
        logger.warning("Task %s reports an unreadable total_cost", task.id, exc_info=True)
        return None


def _dashboard_task(task: TaskORM, agent_names: dict[UUID, str]) -> DashboardTask:
    finished = task.completed_at or (
        task.updated_at if task.status in FINISHED_TASK_STATUSES else None
    )
    return DashboardTask(
        task_id=task.id,
        agent_id=task.agent_id,
        agent_name=agent_names.get(task.agent_id),
        title=(task.description or "")[:200],
        status=task.status,
        started_at=task.started_at or task.created_at,
        finished_at=finished,
        cost_usd=_task_cost(task),
    )


def _connection_error(error: object) -> str | None:
    if isinstance(error, dict):
        message = error.get("message")
        return message if isinstance(message, str) else None
    return error if isinstance(error, str) else None


async def _build_health(factory: RepositoryFactory, agent_names: dict[UUID, str]) -> Health:
    """The workspace's own connections and triggers that stopped working."""
    connections = []
    for instance in await factory.create_repository(MCPServerInstanceRepository).list_failing(
        HEALTH_LIST_LIMIT
    ):
        verification = instance.verification or {}
        if verification.get("status") == "failed":
            reason, state = "verification_failed", verification
        else:
            reason, state = "last_call_failed", instance.last_dispatch or {}
        connections.append(
            BrokenConnection(
                instance_id=instance.id,
                name=instance.name,
                reason=reason,
                error=_connection_error(state.get("error")),
                at=state.get("at"),
            )
        )

    triggers = []
    for trigger in await factory.create_repository(TriggerRepository).list_broken(
        HEALTH_LIST_LIMIT
    ):
        if trigger.needs_new_owner_at is not None:
            trigger_reason = "needs_owner"
        elif trigger.is_active:
            trigger_reason = "failing"
        else:
            trigger_reason = "stopped_after_failures"
        triggers.append(
            BrokenTrigger(
                trigger_id=trigger.id,
                name=trigger.name,
                agent_id=trigger.agent_id,
                agent_name=agent_names.get(trigger.agent_id),
                reason=trigger_reason,
                consecutive_failures=trigger.consecutive_failures,
                failure_threshold=trigger.failure_threshold,
                last_execution_at=trigger.last_execution_at,
            )
        )
    return Health(connections=connections, triggers=triggers)


async def _runtime_usage(workspace_id: str, since: datetime) -> RuntimeUsage | None:
    source = get_workspace_usage_source()
    if source is None:
        return None
    usage = await source.usage_since(workspace_id, since)
    return RuntimeUsage(
        cpu_core_hours=usage.cpu_core_hours.quantize(_CENT),
        memory_gib_hours=usage.memory_gib_hours.quantize(_CENT),
        storage_gib=usage.storage_gib.quantize(_CENT),
    )


def _expand_schedule(
    trigger_rows: list[tuple[UUID, str, UUID, str | None, str | None]],
    agent_names: dict[UUID, str],
    now: datetime,
) -> Schedule:
    horizon = now + timedelta(days=SCHEDULE_HORIZON_DAYS)
    listed_limit = SCHEDULE_HORIZON_DAYS * MAX_LISTED_RUNS_PER_DAY
    runs: list[ScheduledRun] = []
    frequent: list[FrequentSchedule] = []
    for trigger_id, name, agent_id, cron_expression, timezone in trigger_rows:
        if not cron_expression:
            continue
        try:
            fires = cron_runs(cron_expression, timezone, now, horizon, limit=listed_limit + 1)
            per_day = runs_per_day(cron_expression) if len(fires) > listed_limit else None
        except ValueError:
            # One bad row must not take the whole dashboard down.
            logger.warning("Trigger %s has an unusable schedule", trigger_id, exc_info=True)
            continue
        agent_name = agent_names.get(agent_id)
        if per_day is not None:
            frequent.append(
                FrequentSchedule(
                    trigger_id=trigger_id,
                    agent_id=agent_id,
                    agent_name=agent_name,
                    title=name,
                    cron_expression=cron_expression,
                    runs_per_day=per_day,
                    next_run_at=fires[0],
                )
            )
            continue
        runs.extend(
            ScheduledRun(
                fires_at=fires_at,
                trigger_id=trigger_id,
                agent_id=agent_id,
                agent_name=agent_name,
                title=name,
            )
            for fires_at in fires
        )

    runs.sort(key=lambda run: run.fires_at)
    frequent.sort(key=lambda item: item.runs_per_day, reverse=True)
    return Schedule(horizon_days=SCHEDULE_HORIZON_DAYS, runs=runs, frequent=frequent)


async def _build_schedule(
    db_session: AsyncSession,
    task_repo: TaskRepository,
    workspace_id: str,
    agent_names: dict[UUID, str],
) -> Schedule:
    triggers_q = (
        select(
            TriggerORM.id,
            TriggerORM.name,
            TriggerORM.agent_id,
            TriggerORM.cron_expression,
            TriggerORM.timezone,
        )
        .where(TriggerORM.workspace_id == workspace_id)
        .where(TriggerORM.is_active.is_(True))
        .where(TriggerORM.cron_expression.isnot(None))
    )
    trigger_rows = [
        (row.id, row.name, row.agent_id, row.cron_expression, row.timezone)
        for row in (await db_session.execute(triggers_q)).all()
    ]
    now = datetime.now(UTC)
    booked = await task_repo.list_scheduled_until(
        SCHEDULED_TASK_STATUSES, now + timedelta(days=SCHEDULE_HORIZON_DAYS)
    )
    task_runs = [
        ScheduledRun(
            # Naive means UTC, as for every stored timestamp.
            fires_at=scheduled_at if scheduled_at.tzinfo else scheduled_at.replace(tzinfo=UTC),
            task_id=task_id,
            agent_id=agent_id,
            agent_name=agent_names.get(agent_id),
            title=(description or "")[:200],
        )
        for task_id, agent_id, description, scheduled_at in booked
    ]
    schedule = (
        await asyncio.to_thread(_expand_schedule, trigger_rows, agent_names, now)
        if trigger_rows
        else Schedule(horizon_days=SCHEDULE_HORIZON_DAYS, runs=[], frequent=[])
    )
    if task_runs:
        schedule.runs = sorted([*schedule.runs, *task_runs], key=lambda run: run.fires_at)
    return schedule


async def _workspace_cap_currencies(
    factory: RepositoryFactory, workspace_id: str, billing_currency: str
) -> set[str]:
    """The currencies the workspace's enabled monthly spend caps count."""
    rules = await factory.create_repository(PolicyRuleRepository).list_rules(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=workspace_id,
        effect=PolicyEffect.CAP,
        target="spend",
        enabled=True,
    )
    return workspace_cap_currencies([rule.params or {} for rule in rules], billing_currency)


async def _get_workspace_policy_cap_usd(
    factory: RepositoryFactory, workspace_id: str
) -> Decimal | None:
    """Read the workspace-scoped monthly spend cap from policy rules."""
    rules = await factory.create_repository(PolicyRuleRepository).list_rules(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=workspace_id,
        effect=PolicyEffect.CAP,
        target="spend",
        enabled=True,
    )
    for rule in rules:
        if _is_monthly_spend_cap(rule):
            amount = (rule.params or {}).get("amount_usd")
            if amount is not None:
                return to_money(amount)
    return None


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    dependencies=[
        unrestricted("members see the spend they generate; the cap that limits it is admin-only")
    ],
)
async def get_dashboard(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> DashboardResponse:
    """Aggregate workspace state for the operator dashboard."""
    factory = RepositoryFactory(db_session, user_context)
    task_repo = factory.create_repository(TaskRepository)
    wallet_repo = factory.create_repository(WalletRepository)

    workspace_id = user_context.workspace_id
    twenty_four_hours_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)

    # ----- spend card -----
    cap_usd = await _get_workspace_policy_cap_usd(factory, workspace_id)
    today_usd = to_money(await task_repo.sum_spend_today())
    mtd_usd = to_money(await task_repo.sum_spend_mtd())
    pct = float(round(mtd_usd / cap_usd * 100, 2)) if cap_usd else None
    billing_currency = get_customer_pricing().currency()
    covered = await _workspace_cap_currencies(factory, workspace_id, billing_currency)
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    cost_lines = factory.create_repository(CostEntryRepository)
    by_currency = await cost_lines.sum_by_currency_since(month_start)
    mtd_estimate = await cost_lines.sum_since(
        month_start, currency=billing_currency, scope=SpendScope(estimate=True)
    )
    spend = SpendCard(
        today_usd=today_usd,
        mtd_usd=mtd_usd,
        cap_usd=cap_usd,
        pct_of_cap=pct,
        projected_eom_usd=None,
        not_covered=[
            CurrencySpend(currency=currency, amount=amount)
            for currency, amount in spend_not_covered(by_currency, covered).items()
        ],
        mtd_estimate_usd=to_money(mtd_estimate),
    )

    # ----- agent name lookup (single query) -----
    agents_q = select(Agent.id, Agent.name).where(Agent.workspace_id == workspace_id)
    agent_rows = (await db_session.execute(agents_q)).all()
    agent_name_by_id: dict[UUID, str] = {row.id: row.name for row in agent_rows}
    top_agents = [
        AgentSpend(agent_id=agent_id, agent_name=agent_name_by_id.get(agent_id), usd=amount)
        for agent_id, amount in await cost_lines.top_agents_since(
            month_start, currency=billing_currency, limit=TOP_AGENTS_LIMIT
        )
    ]

    # ----- blockers: waiting on a person (one query, split by status) -----
    waiting_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status.in_(HITL_TASK_STATUSES + CONTINUATION_TASK_STATUSES))
        .order_by(desc(TaskORM.updated_at))
        .limit(2 * BLOCKER_LIST_LIMIT)
    )
    waiting_rows = (await db_session.execute(waiting_q)).scalars().all()

    def waiting(statuses: tuple[str, ...]) -> list[HitlBlocker]:
        return [
            HitlBlocker(
                task_id=t.id,
                agent_id=t.agent_id,
                agent_name=agent_name_by_id.get(t.agent_id),
                status=t.status,
                description=t.description,
                created_at=t.created_at,
            )
            for t in waiting_rows
            if t.status in statuses
        ][:BLOCKER_LIST_LIMIT]

    hitl = waiting(HITL_TASK_STATUSES)
    awaiting_continuation = waiting(CONTINUATION_TASK_STATUSES)

    # ----- blockers: wallet exhausted -----
    exhausted_wallets = await wallet_repo.list_budget_exhausted()
    wallet_exhausted = [
        WalletExhaustedBlocker(
            agent_id=w.agent_id,
            agent_name=agent_name_by_id.get(w.agent_id),
            budget_usd=to_money(w.service_budget_usd),
            period=w.service_budget_period,
        )
        for w in exhausted_wallets
    ]

    # ----- blockers: blocked and failed in the last 24h (one query) -----
    ended_at = func.coalesce(TaskORM.completed_at, TaskORM.updated_at)
    ended_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status.in_((*BLOCKED_TASK_STATUSES, "failed")))
        .where(ended_at >= twenty_four_hours_ago)
        .order_by(desc(ended_at))
        .limit(2 * BLOCKER_LIST_LIMIT)
    )
    ended_rows = (await db_session.execute(ended_q)).scalars().all()
    blocked_24h = [
        BlockedTaskBlocker(
            task_id=t.id,
            agent_id=t.agent_id,
            agent_name=agent_name_by_id.get(t.agent_id),
            description=t.description,
            error=t.error,
            occurred_at=t.completed_at or t.updated_at,
        )
        for t in ended_rows
        if t.status in BLOCKED_TASK_STATUSES
    ][:BLOCKER_LIST_LIMIT]
    failed_24h = [
        FailedTaskBlocker(
            task_id=t.id,
            agent_id=t.agent_id,
            agent_name=agent_name_by_id.get(t.agent_id),
            error=t.error,
            occurred_at=t.completed_at or t.updated_at,
        )
        for t in ended_rows
        if t.status == "failed"
    ][:BLOCKER_LIST_LIMIT]

    blockers = Blockers(
        hitl=hitl,
        awaiting_continuation=awaiting_continuation,
        blocked_24h=blocked_24h,
        wallet_exhausted=wallet_exhausted,
        failed_24h=failed_24h,
    )

    # ----- tasks: running now, and the latest to finish -----
    active_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status.in_(ACTIVE_TASK_STATUSES))
        .order_by(desc(func.coalesce(TaskORM.started_at, TaskORM.created_at)))
        .limit(TASK_LIST_LIMIT)
    )
    active_tasks = [
        _dashboard_task(t, agent_name_by_id)
        for t in (await db_session.execute(active_q)).scalars().all()
    ]
    # A run already listed as a blocker is not repeated as history.
    shown_as_blockers = {b.task_id for b in (*blocked_24h, *failed_24h)}
    recent_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status.in_(FINISHED_TASK_STATUSES))
        .order_by(desc(ended_at))
        .limit(TASK_LIST_LIMIT + len(shown_as_blockers))
    )
    recent_tasks = [
        _dashboard_task(t, agent_name_by_id)
        for t in (await db_session.execute(recent_q)).scalars().all()
        if t.id not in shown_as_blockers
    ][:TASK_LIST_LIMIT]

    health = await _build_health(factory, agent_name_by_id)
    usage = await _runtime_usage(workspace_id, month_start)

    schedule = await _build_schedule(db_session, task_repo, workspace_id, agent_name_by_id)

    # ----- daily spend (last 30 days, UTC) -----
    spend_since = datetime.now(UTC) - timedelta(days=29)
    spend_since = datetime(spend_since.year, spend_since.month, spend_since.day, tzinfo=UTC)
    spend_by_day = {
        day.isoformat(): amount
        for day, amount in (await task_repo.sum_spend_by_day(spend_since)).items()
    }
    daily_spend = [
        DailySpendPoint(date=day, usd=spend_by_day.get(day, ZERO))
        for day in ((spend_since.date() + timedelta(days=i)).isoformat() for i in range(30))
    ]
    spend.projected_eom_usd = project_month_end(mtd_usd, spend_by_day, datetime.now(UTC))

    return DashboardResponse(
        spend=spend,
        blockers=blockers,
        active_tasks=active_tasks,
        recent_tasks=recent_tasks,
        schedule=schedule,
        daily_spend=daily_spend,
        top_agents=top_agents,
        health=health,
        usage=usage,
    )


class BalanceResponse(BaseModel):
    currency: str
    # True once billing refuses runs on platform-paid models for want of money.
    exhausted: bool
    viewer_is_payer: bool
    # Only the payer is told the amount, and the pace at which it is spent.
    amount: Money | None
    # Everything billing debited per day on average over its recent window.
    spend_per_day: Money | None = None
    # Days the balance covers at that pace; None when nothing was debited lately.
    runway_days: Decimal | None = None


@router.get(
    "/balance",
    response_model=BalanceResponse | None,
    dependencies=[
        unrestricted("every member learns whether runs are paid for; the amount only the payer")
    ],
)
async def get_balance(user_context: UserContextDep) -> BalanceResponse | None:
    """The balance of the account paying for this workspace; null when the deployment sells none."""
    source = get_account_balance_source()
    if source is None:
        return None
    try:
        balance = await source.balance(user_context)
    except HTTPException:
        raise
    except Exception as error:
        logger.error(
            "Balance read failed for workspace %s", user_context.workspace_id, exc_info=True
        )
        raise HTTPException(status_code=503, detail="balance is unavailable") from error
    return BalanceResponse(
        currency=balance.currency,
        exhausted=balance.exhausted,
        viewer_is_payer=balance.viewer_is_payer,
        amount=to_money(balance.amount) if balance.amount is not None else None,
        spend_per_day=to_money(balance.spend_per_day)
        if balance.spend_per_day is not None
        else None,
        runway_days=balance.runway_days,
    )


class WorkspaceSettingsResponse(BaseModel):
    monthly_cap_usd: Money | None


class WorkspaceSettingsUpdate(BaseModel):
    monthly_cap_usd: Money | None = Field(ge=ZERO)


@router.get(
    "/settings",
    response_model=WorkspaceSettingsResponse,
    dependencies=[
        unrestricted(
            "the monthly cap is read beside every agent's spend; changing it is admin-only"
        )
    ],
)
async def get_workspace_settings(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> WorkspaceSettingsResponse:
    """Read the current workspace's settings (cap, etc)."""
    factory = RepositoryFactory(db_session, user_context)
    cap = await _get_workspace_policy_cap_usd(factory, user_context.workspace_id)
    return WorkspaceSettingsResponse(monthly_cap_usd=cap)


@router.put(
    "/settings", response_model=WorkspaceSettingsResponse, dependencies=[requires_workspace_admin()]
)
async def update_workspace_settings(
    payload: WorkspaceSettingsUpdate,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> WorkspaceSettingsResponse:
    """Upsert the current workspace's monthly spend cap as a policy rule."""
    factory = RepositoryFactory(db_session, user_context)
    repo = factory.create_repository(PolicyRuleRepository)
    workspace_id = user_context.workspace_id

    existing = [
        rule
        for rule in await repo.list_rules(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=workspace_id,
            effect=PolicyEffect.CAP,
            target="spend",
        )
        if _is_monthly_spend_cap(rule)
    ]

    if payload.monthly_cap_usd is None:
        for rule in existing:
            if rule.id is not None:
                await repo.delete(rule.id)
        return WorkspaceSettingsResponse(monthly_cap_usd=None)

    params = {"amount_usd": str(payload.monthly_cap_usd), "period": "month"}
    cap = PolicyRule(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=workspace_id,
        target="spend",
        effect=PolicyEffect.CAP,
        params=params,
    )
    try:
        assert_enforceable(cap)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if existing:
        first, *rest = existing
        if first.id is not None:
            await repo.update(first.id, params=params, enabled=True)
        for rule in rest:
            if rule.id is not None:
                await repo.delete(rule.id)
    else:
        await repo.create(cap)

    return WorkspaceSettingsResponse(monthly_cap_usd=payload.monthly_cap_usd)
