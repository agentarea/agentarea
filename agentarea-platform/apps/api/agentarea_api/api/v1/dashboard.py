"""Workspace dashboard endpoint.

Single round-trip aggregate that powers the post-login `/dashboard` page:
spend (today / MTD / cap / projection), org blockers (HITL, wallet
exhausted, failed in last 24h), and per-agent activity rows.

All data is workspace-scoped via UserContext. Live computation against
existing `tasks` and `wallets` tables — no rollup tables in v1.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from agentarea_agents.domain.models import Agent
from agentarea_common.auth import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.money import to_money
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
)
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_wallet.infrastructure.repository import WalletRepository
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Date, Numeric, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/workspace", tags=["dashboard"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class SpendCard(BaseModel):
    today_usd: float
    mtd_usd: float
    cap_usd: float | None
    pct_of_cap: float | None
    projected_eom_usd: float | None
    projection_method: str = "linear-mtd"


class HitlBlocker(BaseModel):
    task_id: UUID
    agent_id: UUID
    agent_name: str
    description: str
    created_at: datetime


class WalletExhaustedBlocker(BaseModel):
    agent_id: UUID
    agent_name: str
    budget_usd: float
    period: str


class FailedTaskBlocker(BaseModel):
    task_id: UUID
    agent_id: UUID
    agent_name: str
    error: str | None
    occurred_at: datetime


class Blockers(BaseModel):
    hitl: list[HitlBlocker]
    wallet_exhausted: list[WalletExhaustedBlocker]
    failed_24h: list[FailedTaskBlocker]


class AgentRow(BaseModel):
    agent_id: UUID
    name: str
    tasks_done_today: int
    tasks_failed_today: int
    recent_task_names: list[str]
    last_activity_at: datetime | None
    cost_today_usd: float
    cost_mtd_usd: float


class DailySpendPoint(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    usd: float


class DailyTaskCounts(BaseModel):
    date: str  # YYYY-MM-DD (UTC)
    completed: int
    failed: int
    input_required: int


class DashboardResponse(BaseModel):
    spend: SpendCard
    blockers: Blockers
    agents: list[AgentRow]
    daily_spend: list[DailySpendPoint]
    daily_tasks: list[DailyTaskCounts]


def _utc_today_start() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day)


def _utc_first_of_month() -> datetime:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, 1)


def _project_eom(mtd_usd: float, now: datetime) -> float | None:
    """Linear extrapolation of MTD spend to the end of the calendar month."""
    if mtd_usd <= 0:
        return 0.0
    days_elapsed = max(now.day, 1)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    days_in_month = (next_month - datetime(now.year, now.month, 1, tzinfo=UTC)).days
    return round(mtd_usd / days_elapsed * days_in_month, 2)


def _is_monthly_spend_cap(rule: PolicyRule) -> bool:
    return (
        rule.effect == PolicyEffect.CAP
        and rule.target == "spend"
        and (rule.params or {}).get("period", "month") == "month"
    )


async def _get_workspace_policy_cap_usd(
    factory: RepositoryFactory, workspace_id: str
) -> float | None:
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
                return float(to_money(amount))
    return None


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> DashboardResponse:
    """Aggregate workspace state for the operator dashboard."""
    factory = RepositoryFactory(db_session, user_context)
    task_repo = factory.create_repository(TaskRepository)
    wallet_repo = factory.create_repository(WalletRepository)

    workspace_id = user_context.workspace_id
    today_start = _utc_today_start()
    month_start = _utc_first_of_month()
    twenty_four_hours_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)

    # ----- spend card -----
    cap_usd = await _get_workspace_policy_cap_usd(factory, workspace_id)
    today_usd = await task_repo.sum_spend_today()
    mtd_usd = await task_repo.sum_spend_mtd()
    pct = round(mtd_usd / cap_usd * 100, 2) if cap_usd else None
    projected = _project_eom(mtd_usd, datetime.now(UTC)) if cap_usd is not None else None
    spend = SpendCard(
        today_usd=round(today_usd, 4),
        mtd_usd=round(mtd_usd, 4),
        cap_usd=cap_usd,
        pct_of_cap=pct,
        projected_eom_usd=projected,
    )

    # ----- agent name lookup (single query) -----
    agents_q = select(Agent.id, Agent.name).where(Agent.workspace_id == workspace_id)
    agent_rows = (await db_session.execute(agents_q)).all()
    agent_name_by_id: dict[UUID, str] = {row.id: row.name for row in agent_rows}

    # ----- blockers: HITL -----
    hitl_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status == "input_required")
        .order_by(desc(TaskORM.updated_at))
        .limit(20)
    )
    hitl_rows = (await db_session.execute(hitl_q)).scalars().all()
    hitl = [
        HitlBlocker(
            task_id=t.id,
            agent_id=t.agent_id,
            agent_name=agent_name_by_id.get(t.agent_id, "unknown"),
            description=t.description,
            created_at=t.created_at,
        )
        for t in hitl_rows
    ]

    # ----- blockers: wallet exhausted -----
    exhausted_wallets = await wallet_repo.list_budget_exhausted()
    wallet_exhausted = [
        WalletExhaustedBlocker(
            agent_id=w.agent_id,
            agent_name=agent_name_by_id.get(w.agent_id, "unknown"),
            budget_usd=float(w.service_budget_usd),
            period=w.service_budget_period,
        )
        for w in exhausted_wallets
    ]

    # ----- blockers: failed in last 24h -----
    failed_q = (
        select(TaskORM)
        .where(TaskORM.workspace_id == workspace_id)
        .where(TaskORM.status == "failed")
        .where(func.coalesce(TaskORM.completed_at, TaskORM.updated_at) >= twenty_four_hours_ago)
        .order_by(desc(func.coalesce(TaskORM.completed_at, TaskORM.updated_at)))
        .limit(20)
    )
    failed_rows = (await db_session.execute(failed_q)).scalars().all()
    failed_24h = [
        FailedTaskBlocker(
            task_id=t.id,
            agent_id=t.agent_id,
            agent_name=agent_name_by_id.get(t.agent_id, "unknown"),
            error=t.error,
            occurred_at=t.completed_at or t.updated_at,
        )
        for t in failed_rows
    ]

    blockers = Blockers(hitl=hitl, wallet_exhausted=wallet_exhausted, failed_24h=failed_24h)

    # ----- per-agent rows -----
    cost_expr = cast(TaskORM.result.op("->>")("total_cost"), Numeric)
    activity_at = func.coalesce(TaskORM.started_at, TaskORM.created_at)

    today_count_expr = func.coalesce(
        func.sum(
            case(
                ((TaskORM.status == "completed") & (activity_at >= today_start), 1),
                else_=0,
            )
        ),
        0,
    )
    failed_count_expr = func.coalesce(
        func.sum(
            case(
                ((TaskORM.status == "failed") & (activity_at >= today_start), 1),
                else_=0,
            )
        ),
        0,
    )
    cost_today_expr = func.coalesce(
        func.sum(case((activity_at >= today_start, cost_expr), else_=0)),
        0,
    )
    cost_mtd_expr = func.coalesce(
        func.sum(case((activity_at >= month_start, cost_expr), else_=0)),
        0,
    )

    agg_q = (
        select(
            TaskORM.agent_id.label("agent_id"),
            today_count_expr.label("done_today"),
            failed_count_expr.label("failed_today"),
            func.max(activity_at).label("last_activity"),
            cost_today_expr.label("cost_today"),
            cost_mtd_expr.label("cost_mtd"),
        )
        .where(TaskORM.workspace_id == workspace_id)
        .group_by(TaskORM.agent_id)
    )
    agg_rows = (await db_session.execute(agg_q)).all()
    agg_by_agent = {row.agent_id: row for row in agg_rows}

    # Recent task names (last 3 per agent). One bounded query keeps this
    # cheap; for big workspaces a window query (ROW_NUMBER OVER) is the
    # follow-up — defer until measured.
    recent_q = (
        select(TaskORM.agent_id, TaskORM.description, activity_at.label("activity"))
        .where(TaskORM.workspace_id == workspace_id)
        .order_by(TaskORM.agent_id, desc(activity_at))
        .limit(500)
    )
    recent_rows = (await db_session.execute(recent_q)).all()
    recent_by_agent: dict[UUID, list[str]] = {}
    for row in recent_rows:
        bucket = recent_by_agent.setdefault(row.agent_id, [])
        if len(bucket) < 3:
            bucket.append(row.description[:120])

    agents: list[AgentRow] = []
    for agent_id, name in agent_name_by_id.items():
        agg = agg_by_agent.get(agent_id)
        agents.append(
            AgentRow(
                agent_id=agent_id,
                name=name,
                tasks_done_today=int(agg.done_today or 0) if agg else 0,
                tasks_failed_today=int(agg.failed_today or 0) if agg else 0,
                recent_task_names=recent_by_agent.get(agent_id, []),
                last_activity_at=agg.last_activity if agg else None,
                cost_today_usd=round(float(agg.cost_today or 0), 4) if agg else 0.0,
                cost_mtd_usd=round(float(agg.cost_mtd or 0), 4) if agg else 0.0,
            )
        )

    # Most-active agents first
    agents.sort(
        key=lambda a: a.last_activity_at or datetime.min,
        reverse=True,
    )

    # ----- daily spend (last 30 days, UTC) -----
    spend_since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=29)
    spend_since = datetime(spend_since.year, spend_since.month, spend_since.day)
    day_col = cast(activity_at, Date).label("day")
    daily_spend_q = (
        select(day_col, func.coalesce(func.sum(cost_expr), 0).label("usd"))
        .where(TaskORM.workspace_id == workspace_id)
        .where(activity_at >= spend_since)
        .group_by("day")
        .order_by("day")
    )
    daily_spend_rows = (await db_session.execute(daily_spend_q)).all()
    spend_by_day = {r.day.isoformat(): float(r.usd or 0) for r in daily_spend_rows}
    daily_spend = [
        DailySpendPoint(
            date=(spend_since.date() + timedelta(days=i)).isoformat(),
            usd=round(
                spend_by_day.get((spend_since.date() + timedelta(days=i)).isoformat(), 0.0),
                4,
            ),
        )
        for i in range(30)
    ]

    # ----- daily task counts (last 14 days, UTC) -----
    tasks_since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=13)
    tasks_since = datetime(tasks_since.year, tasks_since.month, tasks_since.day)
    daily_tasks_q = (
        select(
            day_col,
            func.coalesce(func.sum(case((TaskORM.status == "completed", 1), else_=0)), 0).label(
                "completed"
            ),
            func.coalesce(func.sum(case((TaskORM.status == "failed", 1), else_=0)), 0).label(
                "failed"
            ),
            func.coalesce(
                func.sum(case((TaskORM.status == "input_required", 1), else_=0)), 0
            ).label("input_required"),
        )
        .where(TaskORM.workspace_id == workspace_id)
        .where(activity_at >= tasks_since)
        .group_by("day")
        .order_by("day")
    )
    daily_task_rows = (await db_session.execute(daily_tasks_q)).all()
    tasks_by_day = {
        r.day.isoformat(): (int(r.completed), int(r.failed), int(r.input_required))
        for r in daily_task_rows
    }
    daily_tasks = []
    for i in range(14):
        d = (tasks_since.date() + timedelta(days=i)).isoformat()
        c, f, ir = tasks_by_day.get(d, (0, 0, 0))
        daily_tasks.append(DailyTaskCounts(date=d, completed=c, failed=f, input_required=ir))

    return DashboardResponse(
        spend=spend,
        blockers=blockers,
        agents=agents,
        daily_spend=daily_spend,
        daily_tasks=daily_tasks,
    )


class WorkspaceSettingsResponse(BaseModel):
    monthly_cap_usd: float | None


class WorkspaceSettingsUpdate(BaseModel):
    monthly_cap_usd: float | None


@router.get("/settings", response_model=WorkspaceSettingsResponse)
async def get_workspace_settings(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> WorkspaceSettingsResponse:
    """Read the current workspace's settings (cap, etc)."""
    factory = RepositoryFactory(db_session, user_context)
    cap = await _get_workspace_policy_cap_usd(factory, user_context.workspace_id)
    return WorkspaceSettingsResponse(monthly_cap_usd=cap)


@router.put("/settings", response_model=WorkspaceSettingsResponse)
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

    params = {"amount_usd": str(to_money(payload.monthly_cap_usd)), "period": "month"}
    if existing:
        first, *rest = existing
        await repo.update(first.id, params=params, enabled=True)
        for rule in rest:
            if rule.id is not None:
                await repo.delete(rule.id)
    else:
        await repo.create(
            PolicyRule(
                subject_type=PolicySubjectType.WORKSPACE,
                subject_id=workspace_id,
                target="spend",
                effect=PolicyEffect.CAP,
                params=params,
            )
        )

    return WorkspaceSettingsResponse(
        monthly_cap_usd=float(to_money(payload.monthly_cap_usd)),
    )
