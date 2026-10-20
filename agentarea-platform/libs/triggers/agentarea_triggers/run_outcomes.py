"""The ``trigger-outcomes`` group on ``tasks.events``: a fired task's end counts towards its trigger.

A firing starts a task and cannot know how the task ends. This group reads the
end of every task a trigger started: a completed task resets the trigger's
consecutive failures, a failed one marks the firing failed and counts towards
``failure_threshold``, which disables the trigger once reached. A cancelled task
counts neither way: a person stopped it.
"""

import logging
from collections.abc import Callable
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_common.events.contract import TASK_COMPLETED, TASK_FAILED
from agentarea_common.events.ports import IntegrationEvent, UnprocessableEventError
from agentarea_common.events.task_stream import WORKSPACE_EXTENSION
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .infrastructure.causation_repository import load_trigger_origin
from .trigger_service import TriggerService

logger = logging.getLogger(__name__)

TriggerServiceFactory = Callable[[AsyncSession, UserContext], TriggerService]


class TriggerRunOutcomes:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        trigger_service: TriggerServiceFactory,
    ):
        self._session_factory = session_factory
        self._trigger_service = trigger_service

    async def handle(self, message: IntegrationEvent) -> None:
        if message.type not in (TASK_COMPLETED, TASK_FAILED):
            return
        workspace_id = message.extensions.get(WORKSPACE_EXTENSION)
        try:
            task_id = UUID(message.subject or "")
        except ValueError as error:
            raise UnprocessableEventError(f"task event {message.id} names no task") from error
        if not workspace_id:
            raise UnprocessableEventError(f"task event {message.id} names no workspace")
        async with self._session_factory() as session:
            with workspace_scope(workspace_id):
                origin = await load_trigger_origin(session, task_id, workspace_id)
                if origin is None:
                    return
                service = self._trigger_service(
                    session, UserContext(user_id=origin.owner, workspace_id=workspace_id)
                )
                failed = message.type == TASK_FAILED
                error = message.data.get("error") or message.data.get("failure_reason")
                await service.record_run_outcome(
                    origin.trigger_id,
                    task_id,
                    failed=failed,
                    error=str(error) if failed and error else None,
                )
                await session.commit()

    async def give_up(self, message: IntegrationEvent) -> None:
        logger.error(
            "The end of task %s (%s, event %s) was not counted towards its trigger after the "
            + "delivery limit; dead-lettered",
            message.subject,
            message.type,
            message.id,
        )
