"""What a finished trial task did, read from the records the run left behind."""

from typing import Any
from uuid import UUID

from agentarea_common.artifacts.audit import ArtifactEvent
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.orm import TaskEventORM, TaskORM
from sqlalchemy import Column, Integer, MetaData, Numeric, Table, Text, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_evals.suites.checks import TrialOutcome

_summary = Table(
    "task_summary",
    MetaData(),
    Column("task_id", PG_UUID(as_uuid=True)),
    Column("cost_usd", Numeric),
    Column("llm_calls", Integer),
    Column("final_response", Text),
)


def _response(task: TaskORM, final_response: str | None) -> str:
    if final_response:
        return final_response
    result: Any = task.result or {}
    if isinstance(result, dict):
        for key in ("final_response", "response", "result", "output"):
            value = result.get(key)
            if isinstance(value, str):
                return value
    return ""


async def task_status(session: AsyncSession, user_context: UserContext, task_id: UUID) -> str:
    task = await _task(session, user_context, task_id)
    return task.status


async def trial_outcome(
    session: AsyncSession, user_context: UserContext, task_id: UUID
) -> TrialOutcome:
    task = await _task(session, user_context, task_id)
    summary = (
        await session.execute(select(_summary).where(_summary.c.task_id == task_id))
    ).one_or_none()
    tools = (
        await session.execute(
            select(TaskEventORM.data["tool_name"].astext).where(
                TaskEventORM.task_id == task_id,
                TaskEventORM.event_type == "tool.call",
                TaskEventORM.workspace_id == user_context.workspace_id,
            )
        )
    ).scalars()
    artifacts = (
        await session.execute(
            select(ArtifactEvent.path)
            .where(
                ArtifactEvent.task_id == str(task_id),
                ArtifactEvent.workspace_id == user_context.workspace_id,
            )
            .distinct()
        )
    ).scalars()
    return TrialOutcome(
        status=task.status,
        response=_response(task, summary.final_response if summary else None),
        cost_usd=float(summary.cost_usd or 0) if summary else 0.0,
        iterations=int(summary.llm_calls or 0) if summary else 0,
        tools_called=[name for name in tools if name],
        artifacts=list(artifacts),
    )


async def _task(session: AsyncSession, user_context: UserContext, task_id: UUID) -> TaskORM:
    task = (
        await session.execute(
            select(TaskORM).where(
                TaskORM.id == task_id, TaskORM.workspace_id == user_context.workspace_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise LookupError(f"trial task {task_id} not found")
    return task
