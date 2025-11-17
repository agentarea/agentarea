import logging
from typing import Any
from uuid import UUID

from agentarea_api.api.events.event_types import EventType
from faststream.redis.fastapi import RedisRouter

logger = logging.getLogger(__name__)


def register_task_event_handlers(router: RedisRouter) -> None:
    """Register task event handlers with the FastStream router."""

    @router.subscriber(EventType.TASK_CREATED.value)
    async def handle_task_created_event(message: dict[str, Any]) -> None:
        """Handle TaskCreated events by starting a Temporal workflow."""
        logger.info(f"Received TaskCreated event: {message}")

        try:
            # Debug: Log the full structure to understand the message format
            logger.debug(f"Event message keys: {list(message.keys())}")
            logger.debug(f"Event data content: {message.get('data', {})}")

            # Extract event data from multiple possible structures
            event_data = message.get("data", {})

            # Try to get values from data field first, then fall back to message root
            task_id = event_data.get("task_id") or message.get("task_id")
            agent_id = event_data.get("agent_id") or message.get("agent_id")
            description = event_data.get("description") or message.get("description", "")
            parameters = event_data.get("parameters") or message.get("parameters", {})
            metadata = event_data.get("metadata") or message.get("metadata", {})

            # Additional fallback: check if we have a TaskCreated event object structure
            if not task_id and hasattr(message, "task_id"):
                task_id = getattr(message, "task_id", None)
            if not agent_id and hasattr(message, "agent_id"):
                agent_id = getattr(message, "agent_id", None)

            logger.debug(
                f"Extracted data: task_id={task_id}, agent_id={agent_id}, description={description}"
            )

            if not task_id or not agent_id:
                logger.error(
                    f"Missing required fields in TaskCreated event: "
                    f"task_id={task_id}, agent_id={agent_id}"
                )
                logger.debug(f"Full event message: {message}")
                return

            # Convert agent_id to UUID if it's a string
            if isinstance(agent_id, str):
                try:
                    agent_id = UUID(agent_id)
                except ValueError as e:
                    logger.error(f"Invalid agent_id format: {agent_id}, error: {e}")
                    return

            logger.info(f"Starting Temporal workflow for task {task_id} with agent {agent_id}")

            # Start Temporal workflow instead of executing directly
            await _start_temporal_workflow_for_task(
                agent_id=agent_id,
                task_id=task_id,
                description=description,
                parameters=parameters,
                metadata=metadata,
            )

            logger.info(f"Temporal workflow started for task {task_id}")

        except Exception as e:
            logger.error(f"Error handling TaskCreated event: {e}", exc_info=True)


async def _start_temporal_workflow_for_task(
    agent_id: UUID,
    task_id: str,
    description: str,
    parameters: dict[str, Any],
    metadata: dict[str, Any],
):
    """Start a Temporal workflow for the agent task."""
    try:
        # Import the temporal workflow service
        from agentarea_agents.application.temporal_workflow_service import (
            TemporalWorkflowService,
        )

        # Create workflow service
        workflow_service = TemporalWorkflowService()

        # Get user_id from metadata - require it, don't default
        user_id = metadata.get("user_id")
        if not user_id:
            logger.error(f"TaskCreated event missing user_id in metadata for task {task_id}")
            # Try to extract from task if available, otherwise fail
            # For now, log error but continue - workflow should handle missing user_id
            user_id = None

        # Start the Temporal workflow - this returns immediately
        result = await workflow_service.execute_agent_task_async(
            agent_id=agent_id,
            task_query=description,
            user_id=user_id,
            task_parameters=parameters,
        )
        execution_id = result.get("execution_id")

        logger.info(
            f"Started Temporal workflow for task {task_id} with execution ID: {execution_id}"
        )

    except Exception as e:
        # Handle workflow already started error gracefully
        if "Workflow execution already started" in str(e) or "WorkflowAlreadyStartedError" in str(
            e
        ):
            logger.info(
                f"Workflow for task {task_id} is already running - "
                "this is expected for duplicate events"
            )
        else:
            logger.error(f"Error starting Temporal workflow for task {task_id}: {e}", exc_info=True)
            raise
