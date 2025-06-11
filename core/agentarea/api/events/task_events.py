import logging
from typing import Any
from uuid import UUID

from faststream.redis.fastapi import RedisRouter

from agentarea.api.events.event_types import EventType

logger = logging.getLogger(__name__)


def register_task_event_handlers(router: RedisRouter) -> None:
    """Register task event handlers with the FastStream router."""

    @router.subscriber(EventType.TASK_CREATED.value)
    async def handle_task_created_event(message: dict[str, Any]) -> None:
        """Handle TaskCreated events by triggering agent execution."""
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
            if not task_id and hasattr(message, 'task_id'):
                task_id = getattr(message, 'task_id', None)
            if not agent_id and hasattr(message, 'agent_id'):
                agent_id = getattr(message, 'agent_id', None)

            logger.debug(f"Extracted data: task_id={task_id}, agent_id={agent_id}, description={description}")

            if not task_id or not agent_id:
                logger.error(f"Missing required fields in TaskCreated event: task_id={task_id}, agent_id={agent_id}")
                logger.debug(f"Full event message: {message}")
                return

            # Convert agent_id to UUID if it's a string
            if isinstance(agent_id, str):
                try:
                    agent_id = UUID(agent_id)
                except ValueError as e:
                    logger.error(f"Invalid agent_id format: {agent_id}, error: {e}")
                    return

            logger.info(f"Starting agent execution for task {task_id} with agent {agent_id}")

            # Create task execution service with dependencies for this event
            task_execution_service = await _create_task_execution_service()

            if not task_execution_service:
                logger.error("Could not create task execution service for event processing")
                return

            await task_execution_service.execute_task(
                    task_id=task_id,
                    agent_id=agent_id,
                    description=description,
                    user_id=metadata.get("user_id"),  # Extract user_id from metadata if available
                    task_parameters=parameters,
                    metadata=metadata
                )

            logger.info(f"Agent execution task created for task {task_id}")

        except Exception as e:
            logger.error(f"Error handling TaskCreated event: {e}", exc_info=True)


async def _create_task_execution_service():
    """Create task execution service with all available dependencies."""
    try:
        # Import dependencies
        from agentarea.api.deps.events import get_event_broker
        from agentarea.api.deps.session import get_session_service
        from agentarea.modules.agents.application.task_execution_service import TaskExecutionService

        # Get dependencies
        session_service = await get_session_service()
        event_broker = await get_event_broker()

        # Try to get database dependencies if available
        agent_repository = None
        llm_service = None
        mcp_service = None

        try:
            from agentarea.api.deps.services import (
                get_llm_model_instance_service,
                get_mcp_server_instance_service,
                get_secret_manager,
            )
            from agentarea.common.infrastructure.database import get_db_session
            from agentarea.modules.agents.infrastructure.repository import AgentRepository

            # Try to get database session
            async for db_session in get_db_session():
                agent_repository = AgentRepository(db_session)
                secret_manager = await get_secret_manager()
                llm_service = await get_llm_model_instance_service(
                    session=db_session,
                    event_broker=event_broker,
                    secret_manager=secret_manager
                )
                mcp_service = await get_mcp_server_instance_service(
                    session=db_session,
                    event_broker=event_broker
                )
                logger.debug("Created task execution service with full dependencies")
                break
        except Exception as db_error:
            logger.debug(f"Database dependencies not available, using minimal setup: {db_error}")

        # Create task execution service (with or without database dependencies)
        task_execution_service = TaskExecutionService(
            agent_repository=agent_repository,
            event_broker=event_broker,
            llm_model_instance_service=llm_service,
            mcp_server_instance_service=mcp_service,
            session_service=session_service
        )

        return task_execution_service

    except Exception as e:
        logger.error(f"Failed to create task execution service: {e}", exc_info=True)
        return None
