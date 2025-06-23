import logging
from typing import Any
from uuid import UUID

from faststream.redis.fastapi import RedisRouter
from sqlalchemy.ext.asyncio import AsyncSession

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
            if not task_id and hasattr(message, "task_id"):
                task_id = getattr(message, "task_id", None)
            if not agent_id and hasattr(message, "agent_id"):
                agent_id = getattr(message, "agent_id", None)

            logger.debug(
                f"Extracted data: task_id={task_id}, agent_id={agent_id}, description={description}"
            )

            if not task_id or not agent_id:
                logger.error(
                    f"Missing required fields in TaskCreated event: task_id={task_id}, agent_id={agent_id}"
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

            logger.info(f"Starting agent execution for task {task_id} with agent {agent_id}")

            # Execute the task with proper session management
            await _execute_agent_task_with_session(
                agent_id=agent_id,
                task_id=task_id,
                description=description,
                parameters=parameters,
                metadata=metadata,
            )

            logger.info(f"Agent execution completed for task {task_id}")

        except Exception as e:
            logger.error(f"Error handling TaskCreated event: {e}", exc_info=True)


async def _execute_agent_task_with_session(
    agent_id: UUID,
    task_id: str,
    description: str,
    parameters: dict[str, Any],
    metadata: dict[str, Any],
):
    """Execute agent task with proper session management."""
    from agentarea.common.infrastructure.database import db

    # Use the database session context manager for proper lifecycle management
    async with db.session() as db_session:
        # Create agent runner service with this session
        agent_runner_service = await _create_agent_runner_service_with_session(db_session)

        if not agent_runner_service:
            logger.error("Could not create agent runner service for event processing")
            return

        # Execute the task directly using AgentRunnerService
        user_id = metadata.get("user_id", "system")
        query = description or "Execute the assigned task"

        # Execute the task and consume all events
        async for event in agent_runner_service.run_agent_task(
            agent_id=agent_id,
            task_id=task_id,
            user_id=user_id,
            query=query,
            task_parameters=parameters,
            enable_agent_communication=True,
        ):
            # Log the event for debugging
            logger.debug(f"Task {task_id} event: {event.get('event_type', 'Unknown')}")


async def _create_agent_runner_service_with_session(db_session: AsyncSession):
    """Create agent runner service with a provided database session."""
    try:
        # Import dependencies
        from agentarea.api.deps.events import get_event_broker
        from agentarea.api.deps.session import get_session_service
        from agentarea.api.deps.services import get_secret_manager
        from agentarea.modules.agents.infrastructure.repository import AgentRepository
        from agentarea.modules.agents.application.agent_builder_service import AgentBuilderService
        from agentarea.modules.agents.application.agent_runner_service import AgentRunnerService
        from agentarea.modules.llm.application.service import LLMModelInstanceService
        from agentarea.modules.llm.infrastructure.llm_model_instance_repository import (
            LLMModelInstanceRepository,
        )
        from agentarea.modules.mcp.application.service import MCPServerInstanceService
        from agentarea.modules.mcp.infrastructure.repository import (
            MCPServerRepository,
            MCPServerInstanceRepository,
        )

        # Get basic dependencies
        event_broker = await get_event_broker()
        session_service = await get_session_service()
        secret_manager = await get_secret_manager()

        # Create repositories with the provided session
        agent_repository = AgentRepository(db_session)
        llm_model_instance_repository = LLMModelInstanceRepository(db_session)
        mcp_server_repository = MCPServerRepository(db_session)
        mcp_server_instance_repository = MCPServerInstanceRepository(db_session)

        # Create services
        llm_model_instance_service = LLMModelInstanceService(
            repository=llm_model_instance_repository,
            event_broker=event_broker,
            secret_manager=secret_manager,
        )

        mcp_server_instance_service = MCPServerInstanceService(
            repository=mcp_server_instance_repository,
            event_broker=event_broker,
            mcp_server_repository=mcp_server_repository,
            secret_manager=secret_manager,
        )

        # Create agent builder service
        agent_builder_service = AgentBuilderService(
            repository=agent_repository,
            event_broker=event_broker,
            llm_model_instance_service=llm_model_instance_service,
            mcp_server_instance_service=mcp_server_instance_service,
        )

        # Create agent runner service (without agent communication to avoid circular dependency)
        agent_runner_service = AgentRunnerService(
            repository=agent_repository,
            event_broker=event_broker,
            llm_model_instance_service=llm_model_instance_service,
            session_service=session_service,
            agent_builder_service=agent_builder_service,
            agent_communication_service=None,  # No A2A communication in event handlers to avoid complexity
        )

        return agent_runner_service

    except Exception as e:
        logger.error(f"Error creating agent runner service: {e}", exc_info=True)
        return None
