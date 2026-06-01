"""Per-agent overview endpoint.

Returns time-series and upcoming-work data for the agent landing page:
- daily spend (last 30 days, UTC)
- daily task counts by status (last 14 days, UTC)
- next-N firings for active cron triggers (next 7 days, UTC)
- pending/running tasks not yet completed
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from agentarea_common.auth import UserContextDep
from agentarea_common.infrastructure.database import get_db_session
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_triggers.infrastructure.orm import TriggerORM
from croniter import croniter
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Date, Numeric, case, cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/agents/{agent_id}", tags=["dashboard"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class DailySpendPoint(BaseModel):
    date: str
    usd: float


class DailyTaskCounts(BaseModel):
    date: str
    completed: int
    failed: int
    input_required: int


class UpcomingItem(BaseModel):
    fires_at: datetime
    kind: str  # "trigger" | "pending_task" | "running_task"
    title: str
    trigger_id: UUID | None = None
    task_id: UUID | None = None
    cron_expression: str | None = None


class AgentOverviewResponse(BaseModel):
    cost_today_usd: float
    cost_mtd_usd: float
    tasks_done_today: int
    tasks_failed_today: int
    last_activity_at: datetime | None
    daily_spend: list[DailySpendPoint]
    daily_tasks: list[DailyTaskCounts]
    upcoming: list[UpcomingItem]


@router.get("/overview", response_model=AgentOverviewResponse)
async def get_agent_overview(
    agent_id: UUID,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> AgentOverviewResponse:
    """Aggregate stats + upcoming work for one agent."""
    workspace_id = user_context.workspace_id
    now = datetime.now(UTC).replace(tzinfo=None)
    today_start = datetime(now.year, now.month, now.day)
    month_start = datetime(now.year, now.month, 1)

    cost_expr = cast(TaskORM.result.op("->>")("total_cost"), Numeric)
    activity_at = func.coalesce(TaskORM.started_at, TaskORM.created_at)
    base_filter = (TaskORM.workspace_id == workspace_id) & (TaskORM.agent_id == agent_id)

    # ----- summary metrics -----
    summary_q = select(
        func.coalesce(func.sum(case((activity_at >= today_start, cost_expr), else_=0)), 0).label(
            "cost_today"
        ),
        func.coalesce(func.sum(case((activity_at >= month_start, cost_expr), else_=0)), 0).label(
            "cost_mtd"
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        (TaskORM.status == "completed") & (activity_at >= today_start),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("done_today"),
        func.coalesce(
            func.sum(
                case(
                    (
                        (TaskORM.status == "failed") & (activity_at >= today_start),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("failed_today"),
        func.max(activity_at).label("last_activity"),
    ).where(base_filter)
    summary = (await db_session.execute(summary_q)).one()

    # ----- daily spend (30d) -----
    spend_since = today_start - timedelta(days=29)
    day_col = cast(activity_at, Date).label("day")
    spend_q = (
        select(day_col, func.coalesce(func.sum(cost_expr), 0).label("usd"))
        .where(base_filter)
        .where(activity_at >= spend_since)
        .group_by("day")
        .order_by("day")
    )
    spend_rows = (await db_session.execute(spend_q)).all()
    spend_by_day = {r.day.isoformat(): float(r.usd or 0) for r in spend_rows}
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

    # ----- daily task counts (14d) -----
    tasks_since = today_start - timedelta(days=13)
    counts_q = (
        select(
            day_col,
            func.coalesce(func.sum(case((TaskORM.status == "completed", 1), else_=0)), 0).label(
                "completed"
            ),
            func.coalesce(func.sum(case((TaskORM.status == "failed", 1), else_=0)), 0).label(
                "failed"
            ),
            func.coalesce(
                func.sum(case((TaskORM.status == "input_required", 1), else_=0)),
                0,
            ).label("input_required"),
        )
        .where(base_filter)
        .where(activity_at >= tasks_since)
        .group_by("day")
        .order_by("day")
    )
    count_rows = (await db_session.execute(counts_q)).all()
    counts_by_day = {
        r.day.isoformat(): (int(r.completed), int(r.failed), int(r.input_required))
        for r in count_rows
    }
    daily_tasks = []
    for i in range(14):
        d = (tasks_since.date() + timedelta(days=i)).isoformat()
        c, f, ir = counts_by_day.get(d, (0, 0, 0))
        daily_tasks.append(DailyTaskCounts(date=d, completed=c, failed=f, input_required=ir))

    # ----- upcoming work (next 7 days) -----
    upcoming: list[UpcomingItem] = []
    horizon = now + timedelta(days=7)

    # Active cron triggers — compute next-N fire times within horizon
    triggers_q = (
        select(TriggerORM)
        .where(TriggerORM.workspace_id == workspace_id)
        .where(TriggerORM.agent_id == agent_id)
        .where(TriggerORM.is_active.is_(True))
        .where(TriggerORM.cron_expression.isnot(None))
    )
    trigger_rows = (await db_session.execute(triggers_q)).scalars().all()
    for trig in trigger_rows:
        try:
            itr = croniter(trig.cron_expression, now)
            for _ in range(10):
                fires_at = itr.get_next(datetime)
                if fires_at > horizon:
                    break
                upcoming.append(
                    UpcomingItem(
                        fires_at=fires_at,
                        kind="trigger",
                        title=trig.name,
                        trigger_id=trig.id,
                        cron_expression=trig.cron_expression,
                    )
                )
        except Exception:
            # Bad cron expression — surface as a single hint without dying
            upcoming.append(
                UpcomingItem(
                    fires_at=now,
                    kind="trigger",
                    title=f"{trig.name} (invalid cron)",
                    trigger_id=trig.id,
                    cron_expression=trig.cron_expression,
                )
            )

    # Pending or running tasks — they're already "next on the agenda"
    pending_q = (
        select(TaskORM)
        .where(base_filter)
        .where(TaskORM.status.in_(["pending", "submitted", "running"]))
        .order_by(desc(TaskORM.created_at))
        .limit(20)
    )
    pending_rows = (await db_session.execute(pending_q)).scalars().all()
    for t in pending_rows:
        upcoming.append(
            UpcomingItem(
                fires_at=t.started_at or t.created_at,
                kind="running_task" if t.status == "running" else "pending_task",
                title=t.description[:120] if t.description else "(unnamed task)",
                task_id=t.id,
            )
        )

    upcoming.sort(key=lambda u: u.fires_at)

    return AgentOverviewResponse(
        cost_today_usd=round(float(summary.cost_today or 0), 4),
        cost_mtd_usd=round(float(summary.cost_mtd or 0), 4),
        tasks_done_today=int(summary.done_today or 0),
        tasks_failed_today=int(summary.failed_today or 0),
        last_activity_at=summary.last_activity,
        daily_spend=daily_spend,
        daily_tasks=daily_tasks,
        upcoming=upcoming,
    )
