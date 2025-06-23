"""Task Execution Service for coordinating task events with agent execution."""

import asyncio
import logging
from typing import Any
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from agentarea_llm.application.service import LLMModelInstanceService
from agentarea_mcp.application.service import MCPServerInstanceService

from agentarea_agents.infrastructure.repository import AgentRepository

from .agent_builder_service import AgentBuilderService
from .agent_communication_service import AgentCommunicationService
from .agent_runner_service import AgentRunnerService

logger = logging.getLogger(__name__)


class TaskExecutionService:
    """Service for coordinating task execution with agents.

    This is a thin wrapper around AgentRunnerService that provides
    a simple interface for task execution from event handlers.
    """

    def __init__(
        self,
        agent_repository: AgentRepository | None,
        event_broker: EventBroker,
        llm_model_instance_service: LLMModelInstanceService | None,
        mcp_server_instance_service: MCPServerInstanceService | None = None,
        session_service: Any | None = None,
        agent_communication_service: AgentCommunicationService | None = None,
    ):
        self.agent_repository = agent_repository
        self.event_broker = event_broker
        self.llm_model_instance_service = llm_model_instance_service
        self.mcp_server_instance_service = mcp_server_instance_service
        self.session_service = session_service
        self.agent_communication_service = agent_communication_service

        # Initialize agent builder service only if required dependencies are available
        self.agent_builder_service = None
        if agent_repository and llm_model_instance_service:
            self.agent_builder_service = AgentBuilderService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_model_instance_service,
                mcp_server_instance_service=mcp_server_instance_service,
            )

        # Initialize agent runner service only if all dependencies are available
        self.agent_runner_service = None
        if (
            self.agent_builder_service
            and session_service
            and agent_repository
            and llm_model_instance_service
        ):
            self.agent_runner_service = AgentRunnerService(
                repository=agent_repository,
                event_broker=event_broker,
                llm_model_instance_service=llm_model_instance_service,
                session_service=session_service,
                agent_builder_service=self.agent_builder_service,
                agent_communication_service=agent_communication_service,
            )

    async def execute_task(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Execute a task with the specified agent.

        This method delegates to AgentRunnerService for the actual execution
        and handles the event streaming in the background.

        Args:
            task_id: Unique task identifier
            agent_id: UUID of the agent to execute the task
            description: Task description/query
            user_id: User ID requesting the task (defaults to 'system')
            task_parameters: Additional task parameters
            metadata: Task metadata
        """
        if not self.agent_runner_service:
            logger.error(
                "Agent runner service not available - session service and dependencies required"
            )
            return

        try:
            # Ensure user_id is not None
            effective_user_id = (
                user_id or (metadata.get("user_id") if metadata else None) or "system"
            )
            query = description or "Execute the assigned task"

            logger.info(f"Starting task execution: {task_id} for agent {agent_id}")

            # Check if we have an override for agent-to-agent communication
            enable_comm: bool | None = None
            if metadata is not None and "enable_agent_communication" in metadata:
                enable_comm = bool(metadata.get("enable_agent_communication"))

            # Execute the task using AgentRunnerService
            # The AgentRunnerService already handles all event publishing internally
            async for event in self.agent_runner_service.run_agent_task(
                agent_id=agent_id,
                task_id=task_id,
                user_id=effective_user_id,
                query=query,
                task_parameters=task_parameters or {},
                enable_agent_communication=enable_comm,
            ):
                # Just log the events - AgentRunnerService already publishes them to the event broker
                logger.debug(f"Task event: {event.get('event_type', 'Unknown')} for task {task_id}")

        except Exception as e:
            logger.error(
                f"Error executing task {task_id} with agent {agent_id}: {e}", exc_info=True
            )

    def execute_task_async(
        self,
        task_id: str,
        agent_id: UUID,
        description: str,
        user_id: str | None = None,
        task_parameters: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "asyncio.Task[None]":
        """Execute a task asynchronously and return the task handle.

        This method creates a background task for execution without blocking.
        """
        return asyncio.create_task(
            self.execute_task(
                task_id=task_id,
                agent_id=agent_id,
                description=description,
                user_id=user_id,
                task_parameters=task_parameters,
                metadata=metadata,
            )
        )

    async def get_agent_config(self, agent_id: UUID) -> dict[str, Any] | None:
        """Get agent configuration for the specified agent."""
        if not self.agent_builder_service:
            logger.error("Agent builder service not available - cannot get agent config")
            return None
        return await self.agent_builder_service.build_agent_config(agent_id)

    async def validate_agent(self, agent_id: UUID) -> list[str]:
        """Validate agent configuration and return any errors."""
        if not self.agent_builder_service:
            return ["Agent builder service not available"]
        return await self.agent_builder_service.validate_agent_config(agent_id)

    async def get_agent_capabilities(self, agent_id: UUID) -> dict[str, Any]:
        """Get agent capabilities."""
        if not self.agent_builder_service:
            logger.error("Agent builder service not available - cannot get agent capabilities")
            return {}
        return await self.agent_builder_service.get_agent_capabilities(agent_id)
