"""Check that a delivery's trigger belongs to the workspace of the task it answers.

Adapters send with ``channel_cred:<type>:<trigger_id>`` and the secret reader
takes the workspace from that trigger, not from the task. Without this check a
channel_origin naming another workspace's trigger replied with that workspace's
bot token.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class TriggerWorkspaceGuard:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(self, channel_config: dict[str, Any]) -> bool:
        from agentarea_tasks.infrastructure.orm import TaskORM

        from agentarea_triggers.infrastructure.orm import TriggerORM

        trigger_id = channel_config.get("trigger_id")
        if not trigger_id:
            return True
        task_id = channel_config.get("task_id")
        try:
            trigger_uuid = UUID(str(trigger_id))
            task_uuid = UUID(str(task_id))
        except ValueError:
            logger.exception(
                "Refusing channel delivery: unparseable trigger_id=%r or task_id=%r",
                trigger_id,
                task_id,
            )
            return False

        async with self._session_factory() as session:
            trigger_workspace = await session.scalar(
                select(TriggerORM.workspace_id).where(TriggerORM.id == trigger_uuid)
            )
            task_workspace = await session.scalar(
                select(TaskORM.workspace_id).where(TaskORM.id == task_uuid)
            )
        if trigger_workspace is None or task_workspace is None:
            logger.error(
                "Refusing channel delivery: trigger %s or task %s does not exist",
                trigger_uuid,
                task_uuid,
            )
            return False
        if str(trigger_workspace) != str(task_workspace):
            logger.error(
                "Refusing channel delivery: trigger %s is in workspace %s, task %s is in %s",
                trigger_uuid,
                trigger_workspace,
                task_uuid,
                task_workspace,
            )
            return False
        return True
