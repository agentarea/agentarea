"""Agent Execution Service for running agent tasks."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.types import TaskState
from agentarea_tasks.domain.events import TaskCompleted, TaskFailed, TaskStatusChanged
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types

from .agent_builder_service import AgentBuilderService
from .agent_factory_service import AgentFactoryService

logger = logging.getLogger(__name__)


class AgentExecutionService:
    """Service responsible for executing agent tasks with proper event handling."""

    def __init__(
        self,
        event_broker: EventBroker,
        session_service: BaseSessionService,
        agent_builder_service: AgentBuilderService,
        agent_factory_service: AgentFactoryService,
        agent_communication_service: Any | None = None,
    ):
        self.event_broker = event_broker
        self.session_service = session_service
        self.agent_builder_service = agent_builder_service
        self.agent_factory_service = agent_factory_service
        self.agent_communication_service = agent_communication_service

    async def execute_agent_task(
        self,
        agent_id: UUID,
        task_id: str,
        user_id: str,
        query: str,
        task_parameters: dict[str, Any] | None = None,
        enable_agent_communication: bool | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute an agent task and yield events.

        Args:
            agent_id: UUID of the agent to run
            task_id: Task identifier
            user_id: User running the task
            query: Query/instruction for the task
            task_parameters: Additional task parameters
            enable_agent_communication: Override flag to enable/disable A2A communication

        Yields:
            Task execution events
        """
        try:
            # Validate agent configuration
            validation_errors = await self.agent_builder_service.validate_agent_config(agent_id)
            if validation_errors:
                error_msg = f"Agent validation failed: {', '.join(validation_errors)}"
                logger.error(error_msg)
                await self._publish_task_failed(task_id, error_msg, "AGENT_VALIDATION_ERROR")
                yield self._create_task_event("TaskFailed", task_id, agent_id, error_message=error_msg, error_code="AGENT_VALIDATION_ERROR")
                return

            # Build agent configuration
            agent_config = await self.agent_builder_service.build_agent_config(agent_id)
            if not agent_config:
                error_msg = f"Failed to build agent configuration for agent {agent_id}"
                logger.error(error_msg)
                await self._publish_task_failed(task_id, error_msg, "AGENT_CONFIG_ERROR")
                yield self._create_task_event("TaskFailed", task_id, agent_id, error_message=error_msg, error_code="AGENT_CONFIG_ERROR")
                return

            logger.info(f"Starting task {task_id} for agent {agent_config['name']} (ID: {agent_id})")

            # Log execution mode
            execution_mode = "Temporal" if self.agent_factory_service.enable_temporal_execution else "Standard"
            logger.info(f"Using {execution_mode} execution mode for agent {agent_id}")

            # Publish TaskStatusChanged event
            status_event = TaskStatusChanged(
                task_id=task_id,
                old_status=TaskState.PENDING,
                new_status=TaskState.RUNNING,
                message=f"Starting task execution for agent {agent_config['name']}",
            )
            await self.event_broker.publish(status_event)

            yield self._create_task_event("TaskStatusChanged", task_id, agent_id, status="running", message=f"Starting task execution for agent {agent_config['name']}")

            # Create and run agent
            async for event in self._execute_agent_with_config(agent_id, agent_config, task_id, user_id, query, task_parameters, enable_agent_communication):
                yield event

        except Exception as e:
            error_msg = f"Failed to execute task {task_id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await self._publish_task_failed(task_id, error_msg, "EXECUTION_ERROR")
            yield self._create_task_event("TaskFailed", task_id, agent_id, error_message=error_msg, error_code="EXECUTION_ERROR")

    async def _execute_agent_with_config(
        self,
        agent_id: UUID,
        agent_config: dict[str, Any],
        task_id: str,
        user_id: str,
        query: str,
        task_parameters: dict[str, Any] | None,
        enable_agent_communication: bool | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Execute agent with the given configuration."""
        
        # Create LiteLLM model
        model_instance = agent_config["model_instance"]
        litellm_model_string, endpoint_url = self.agent_factory_service.create_litellm_model_from_instance(model_instance)

        litellm_model = LiteLlm(
            model=litellm_model_string,
            api_base=endpoint_url,
            generation_config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=8192,
            ),
        )

        # Build tools (placeholder - implement MCP tool building)
        tools = []  # TODO: Implement tool building from agent_config["tools_config"]

        # Create agent instance using factory
        agent = self.agent_factory_service.create_llm_agent(agent_id, agent_config, tools, litellm_model)

        # Run agent
        runner = Runner(agent, session_service=self.session_service)
        
        async for runner_event in runner.run_async(user_id=user_id, query=query):
            # Convert runner events to task events
            task_event = self._convert_runner_event_to_task_event(runner_event, task_id, agent_id)
            if task_event:
                yield task_event

        # Task completed successfully
        completed_event = TaskCompleted(
            task_id=task_id,
            result={"message": "Task completed successfully"},
        )
        await self.event_broker.publish(completed_event)
        
        yield self._create_task_event("TaskCompleted", task_id, agent_id, result={"message": "Task completed successfully"})

    def _convert_runner_event_to_task_event(self, runner_event: Any, task_id: str, agent_id: UUID) -> dict[str, Any] | None:
        """Convert Google ADK runner event to task event format."""
        # TODO: Implement proper event conversion based on runner_event type
        return {
            "event_type": "AgentEvent",
            "task_id": task_id,
            "agent_id": str(agent_id),
            "content": str(runner_event),  # Placeholder - implement proper conversion
        }

    def _create_task_event(self, event_type: str, task_id: str, agent_id: UUID, **kwargs) -> dict[str, Any]:
        """Create a standardized task event."""
        return {
            "event_type": event_type,
            "task_id": task_id,
            "agent_id": str(agent_id),
            **kwargs,
        }

    async def _publish_task_failed(self, task_id: str, error_message: str, error_code: str) -> None:
        """Publish a TaskFailed event."""
        failed_event = TaskFailed(
            task_id=task_id,
            error_message=error_message,
            error_code=error_code,
        )
        await self.event_broker.publish(failed_event) 