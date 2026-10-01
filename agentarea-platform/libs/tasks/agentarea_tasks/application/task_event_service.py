"""Task event service for managing workflow events."""

import logging
from datetime import datetime
from uuid import UUID

from agentarea_common.base import RepositoryFactory
from agentarea_common.events.broker import EventBroker

from ..domain.models import TaskEvent
from ..infrastructure.repository import TaskEventRepository

logger = logging.getLogger(__name__)


class TaskEventService:
    """Service for managing task events with proper domain separation."""

    def __init__(
        self,
        repository_factory: RepositoryFactory,
        event_broker: EventBroker | None,
    ):
        self.repository_factory = repository_factory
        self.event_broker = event_broker

    async def create_workflow_event(
        self,
        task_id: UUID,
        event_id: UUID,
        event_type: str,
        data: dict,
        timestamp: datetime,
        workspace_id: str,
        created_by: str,
    ) -> TaskEvent:
        """Persist a workflow event once, keyed by the id the workflow minted.

        Storing the same ``event_id`` again returns the row already stored, so a
        retried publish batch never duplicates history.
        """
        if not workspace_id:
            raise ValueError(f"workspace_id is required for task {task_id} event")
        if not created_by:
            raise ValueError(f"created_by is required for task {task_id} event")

        event = TaskEvent.create_workflow_event(
            task_id=task_id,
            event_id=event_id,
            event_type=event_type,
            data=data,
            timestamp=timestamp,
            workspace_id=workspace_id,
            created_by=created_by,
        )
        task_event_repository = self.repository_factory.create_repository(TaskEventRepository)
        persisted_event = await task_event_repository.create_event(event)
        logger.debug(f"Stored workflow event: {event_type} for task {task_id}")
        return persisted_event

    async def get_task_events(
        self, task_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[TaskEvent]:
        """Get events for a specific task."""
        task_event_repository = self.repository_factory.create_repository(TaskEventRepository)
        return await task_event_repository.get_events_for_task(task_id, limit, offset)

    async def get_events_by_type(
        self, event_type: str, limit: int = 100, offset: int = 0
    ) -> list[TaskEvent]:
        """Get events by type."""
        task_event_repository = self.repository_factory.create_repository(TaskEventRepository)
        return await task_event_repository.get_events_by_type(event_type, limit, offset)
