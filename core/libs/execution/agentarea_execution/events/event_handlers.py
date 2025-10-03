"""Event handlers for workflow events.

This module provides proper event-driven architecture by separating
event publishing from database persistence using domain services.
"""

import logging
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_common.events.base_events import DomainEvent

logger = logging.getLogger(__name__)


class WorkflowEventHandler:
    """Handles workflow events by persisting them using proper domain services."""

    def __init__(self):
        self.database = get_database()

    async def handle_workflow_event(self, event: DomainEvent) -> None:
        """Handle workflow events by persisting to database using TaskEventService.

        This is called by the event system, not directly from activities.
        """
        try:
            from agentarea_tasks.application.task_event_service import TaskEventService

            # Extract task information from event
            task_id = UUID(event.aggregate_id)
            workspace_id = self._extract_workspace_id(event)

            async with self.database.async_session_factory() as session:
                # Create proper user context
                user_context = UserContext(user_id="event_handler", workspace_id=workspace_id)

                # Create service with dependencies
                repository_factory = RepositoryFactory(session, user_context)
                # Note: We don't have event_broker here, but TaskEventService doesn't use it for persistence
                task_event_service = TaskEventService(repository_factory, None)

                # Create event using service
                await task_event_service.create_workflow_event(
                    task_id=task_id,
                    event_type=event.original_event_type or event.event_type,
                    data=event.original_data or {},
                    workspace_id=workspace_id,
                    created_by="event_handler",
                )

                await session.commit()
                logger.debug(
                    f"Persisted workflow event using service: {event.event_type} for task {task_id}"
                )

        except Exception as e:
            logger.error(f"Failed to persist workflow event using service: {e}")
            # Don't re-raise - event persistence failures shouldn't break workflows

    def _extract_workspace_id(self, event: DomainEvent) -> str:
        """Extract workspace ID from event data."""
        if event.original_data and isinstance(event.original_data, dict):
            return event.original_data.get("workspace_id", "default")
        return "default"


class LLMErrorEventHandler:
    """Specialized handler for LLM error events."""

    async def handle_llm_error(self, event: DomainEvent) -> None:
        """Handle LLM error events with specialized logic.

        This can include:
        - Alerting
        - Metrics collection
        - Error analysis
        - Retry logic coordination
        """
        try:
            error_data = event.original_data or {}
            task_id = error_data.get("task_id", "unknown")
            error_type = error_data.get("error_type", "unknown")

            logger.warning(f"LLM error in task {task_id}: {error_type}")

            # Add specialized error handling logic here
            # For example:
            # - Update task status
            # - Send alerts
            # - Collect metrics
            # - Trigger retry logic

        except Exception as e:
            logger.error(f"Failed to handle LLM error event: {e}")


# Global event handlers
_workflow_event_handler = WorkflowEventHandler()
_llm_error_handler = LLMErrorEventHandler()


async def handle_workflow_event(event: DomainEvent) -> None:
    """Global handler for workflow events."""
    await _workflow_event_handler.handle_workflow_event(event)


async def handle_llm_error_event(event: DomainEvent) -> None:
    """Global handler for LLM error events."""
    await _llm_error_handler.handle_llm_error(event)
