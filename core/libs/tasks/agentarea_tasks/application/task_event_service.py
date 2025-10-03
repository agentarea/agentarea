"""Task event service for managing workflow events."""

import logging
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
        event_broker: EventBroker,
    ):
        self.repository_factory = repository_factory
        self.event_broker = event_broker

    async def create_workflow_event(
        self,
        task_id: UUID,
        event_type: str,
        data: dict,
        workspace_id: str = "default",
        created_by: str = "workflow",
    ) -> TaskEvent:
        """Create and persist a workflow event.

        This is the proper way to handle workflow events instead of
        direct database access in activities.
        """
        try:
            # Create domain model
            event = TaskEvent.create_workflow_event(
                task_id=task_id,
                event_type=event_type,
                data=data,
                workspace_id=workspace_id,
                created_by=created_by,
            )

            # Persist using repository
            task_event_repository = self.repository_factory.create_repository(TaskEventRepository)
            persisted_event = await task_event_repository.create_event(event)

            logger.debug(f"Created workflow event: {event_type} for task {task_id}")
            return persisted_event

        except Exception as e:
            logger.error(f"Failed to create workflow event: {e}")
            raise

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

    async def create_multiple_events(self, events_data: list[dict]) -> list[TaskEvent]:
        """Create multiple workflow events efficiently.

        This is useful for batch processing workflow events.
        """
        created_events = []

        for event_data in events_data:
            try:
                event = await self.create_workflow_event(
                    task_id=UUID(event_data["task_id"]),
                    event_type=event_data["event_type"],
                    data=event_data.get("data", {}),
                    workspace_id=event_data.get("workspace_id", "default"),
                    created_by=event_data.get("created_by", "workflow"),
                )
                created_events.append(event)

            except Exception as e:
                logger.error(
                    f"Failed to create event {event_data.get('event_type', 'unknown')}: {e}"
                )
                # Continue processing other events
                continue

        return created_events
