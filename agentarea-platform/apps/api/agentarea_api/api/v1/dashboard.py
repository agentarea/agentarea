"""Workspace dashboard endpoint.

Single round-trip aggregate that powers the post-login `/dashboard` page:
spend (today / MTD / cap / projection), org blockers (HITL, runs waiting to
continue, blocked and failed runs in the last 24h, exhausted wallets),
running and recently finished tasks, and the cron schedule for the weeks ahead.

All data is workspace-scoped via UserContext. Live computation against
existing `tasks` and `wallets` tables — no rollup tables in v1. Money fields
are `Money` (Decimal, serialized as a string), as in the wallet API.
"""

import asyncio
import logging
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
from agentarea_common.money import ZERO, Money, to_money
from agentarea_common.utils.types import UtcDatetime
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
)
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from agentarea_tasks.domain.statuses import TASK_STATUSES, TaskStatus
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_triggers.infrastructure.orm import TriggerORM
from agentarea_wallet.infrastructure.repository import WalletRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import Date, Numeric, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

SCHEDULE_HORIZON_DAYS = 21
# A schedule firing more often than this per day is summarised, not listed.
MAX_LISTED_RUNS_PER_DAY = 3

# Where each stored status shows up on the dashboard. Keyed by the canonical
# vocabulary: a status added there fails this import instead of silently
# vanishing from every panel.
_DashboardPlace = Literal["active", "hitl", "continuation", "blocked", "finished", "unlisted"]
_STATUS_PLACE: dict[TaskStatus, _DashboardPlace] = {
    "submitted": "active",
    "pending": "active",
    "preparing": "active",
    # Booked for a later moment; not work in flight yet.
    "scheduled": "unlisted",
    "running": "active",
    "working": "active",
    "waiting_for_input": "hitl",
    "waiting_for_approval": "hitl",
    "waiting_for_continuation": "continuation",
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
TASK_LIST_LIMIT = 10
BLOCKER_LIST_LIMIT = 20

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]


class SpendCard(BaseModel):
    today_usd: Money
    mtd_usd: Money
    cap_usd: Money | None
    pct_of_cap: float | None
    projected_eom_usd: Money | None
    projection_method: str = "linear-mtd"


class HitlBlocker(BaseModel):
    task_id: UUID
    agent_id: UUID
    # None when the agent no longer resolves — never a fabricated placeholder.
    agent_name: str | None = None
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
    fires_at: UtcDatetime
    trigger_id: UUID
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


class DashboardResponse(BaseModel):
    spend: SpendCard
    blockers: Blockers
    active_tasks: list[DashboardTask]
    recent_tasks: list[DashboardTask]
    schedule: Schedule
    daily_spend: list[DailySpendPoint]


_MONEY = TypeAdapter(Money)
_CENT = Decimal("0.01")


def task_spend_expr() -> ColumnElement[Decimal]:
    """A task's own model spend, as TaskRepository.sum_spend_since sums it.

    ``own_cost`` keeps delegated child spend from counting on the child and
    again in the parent's transitive ``total_cost``; older results only have
    ``total_cost``.
    """
    return func.coalesce(
        cast(TaskORM.result.op("->>")("own_cost"), Numeric),
        cast(TaskORM.result.op("->>")("total_cost"), Numeric),
        0,
    )


def _project_eom(mtd_usd: Decimal, now: datetime) -> Decimal:
    """Linear extrapolation of MTD spend to the end of the calendar month."""
    if mtd_usd <= ZERO:
        return ZERO
    days_elapsed = max(now.day, 1)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    days_in_month = (next_month - datetime(now.year, now.month, 1, tzinfo=UTC)).days
    return (mtd_usd / days_elapsed * days_in_month).quantize(_CENT)


def _is_monthly_spend_cap(rule: PolicyRule) -> bool:
    return (
        rule.effect == PolicyEffect.CAP
        and rule.target == "spend"
        and (rule.params or {}).get("period", "month") == "month"
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
    db_session: AsyncSession, workspace_id: str, agent_names: dict[UUID, str]
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
    if not trigger_rows:
        return Schedule(horizon_days=SCHEDULE_HORIZON_DAYS, runs=[], frequent=[])
    return await asyncio.to_thread(_expand_schedule, trigger_rows, agent_names, datetime.now(UTC))


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
    projected = _project_eom(mtd_usd, datetime.now(UTC)) if cap_usd is not None else None
    spend = SpendCard(
        today_usd=today_usd,
        mtd_usd=mtd_usd,
        cap_usd=cap_usd,
        pct_of_cap=pct,
        projected_eom_usd=projected,
    )

    # ----- agent name lookup (single query) -----
    agents_q = select(Agent.id, Agent.name).where(Agent.workspace_id == workspace_id)
    agent_rows = (await db_session.execute(agents_q)).all()
    agent_name_by_id: dict[UUID, str] = {row.id: row.name for row in agent_rows}

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
    recent_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status.in_(FINISHED_TASK_STATUSES))
        .order_by(desc(ended_at))
        .limit(TASK_LIST_LIMIT)
    )
    recent_tasks = [
        _dashboard_task(t, agent_name_by_id)
        for t in (await db_session.execute(recent_q)).scalars().all()
    ]

    schedule = await _build_schedule(db_session, workspace_id, agent_name_by_id)

    # ----- daily spend (last 30 days, UTC) -----
    spend_since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=29)
    spend_since = datetime(spend_since.year, spend_since.month, spend_since.day)
    activity_at = func.coalesce(TaskORM.started_at, TaskORM.created_at)
    day_col = cast(activity_at, Date).label("day")
    daily_spend_q = (
        select(day_col, func.coalesce(func.sum(task_spend_expr()), 0).label("usd"))
        .where(TaskORM.workspace_id == workspace_id)
        .where(activity_at >= spend_since)
        .group_by("day")
        .order_by("day")
    )
    daily_spend_rows = (await db_session.execute(daily_spend_q)).all()
    spend_by_day = {r.day.isoformat(): to_money(r.usd) for r in daily_spend_rows}
    daily_spend = [
        DailySpendPoint(date=day, usd=spend_by_day.get(day, ZERO))
        for day in ((spend_since.date() + timedelta(days=i)).isoformat() for i in range(30))
    ]

    return DashboardResponse(
        spend=spend,
        blockers=blockers,
        active_tasks=active_tasks,
        recent_tasks=recent_tasks,
        schedule=schedule,
        daily_spend=daily_spend,
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
