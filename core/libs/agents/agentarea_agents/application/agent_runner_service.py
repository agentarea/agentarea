import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from agentarea_common.events.broker import EventBroker
from agentarea_common.utils.types import TaskState

# Legacy import removed - now using new 4-entity architecture
from agentarea_tasks.domain.events import TaskCompleted, TaskFailed, TaskStatusChanged
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.genai import types

from agentarea_agents.infrastructure.repository import AgentRepository

from .agent_builder_service import AgentBuilderService

logger = logging.getLogger(__name__)


class AgentRunnerService:
    def __init__(
        self,
        repository: AgentRepository,
        event_broker: EventBroker,
        session_service: BaseSessionService,
        agent_builder_service: AgentBuilderService,
        agent_communication_service: Any | None = None,
    ):
        self.repository = repository
        self.event_broker = event_broker
        self.session_service = session_service
        self.agent_builder_service = agent_builder_service
        self.agent_communication_service = agent_communication_service

    def _create_litellm_model_from_instance(
        self, model_instance: Any
    ) -> tuple[str, str | None]:
        """Create LiteLLM model string and endpoint URL from database model instance."""
        logger.info(f"Using model instance: {model_instance.name}")

        # Extract endpoint_url from provider_config
        endpoint_url = getattr(
            getattr(model_instance, "provider_config", None), "endpoint_url", None
        )

        # Construct LiteLLM model string from provider_spec and model_spec
        provider_config = getattr(model_instance, "provider_config", None)
        provider_spec = getattr(provider_config, "provider_spec", None)
        model_spec = getattr(model_instance, "model_spec", None)

        if not (provider_spec and model_spec):
            raise ValueError(
                "Model instance relationships not loaded - ensure provider_config, provider_spec, and model_spec are loaded"
            )

        litellm_model_string = f"{provider_spec.provider_type}/{model_spec.model_name}"
        logger.info(f"Created LiteLLM model string: {litellm_model_string}")

        return litellm_model_string, endpoint_url

    async def run_agent_task(
        self,
        agent_id: UUID,
        task_id: str,
        user_id: str,
        query: str,
        task_parameters: dict[str, Any] | None = None,
        enable_agent_communication: bool | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Run an agent to execute a specific task.

        Args:
            agent_id: UUID of the agent to run
            task_id: Task identifier
            user_id: User running the task
            query: Query/instruction for the task
            task_parameters: Additional task parameters
            enable_agent_communication: Override flag to enable/disable A2A communication for this run

        Yields:
            Task execution events
        """
        try:
            # Validate agent configuration
            validation_errors = await self.agent_builder_service.validate_agent_config(
                agent_id
            )
            if validation_errors:
                error_msg = f"Agent validation failed: {', '.join(validation_errors)}"
                logger.error(error_msg)

                # Publish TaskFailed event
                failed_event = TaskFailed(
                    task_id=task_id,
                    error_message=error_msg,
                    error_code="AGENT_VALIDATION_ERROR",
                )
                await self.event_broker.publish(failed_event)

                yield {
                    "event_type": "TaskFailed",
                    "task_id": task_id,
                    "agent_id": str(agent_id),
                    "error_message": error_msg,
                    "error_code": "AGENT_VALIDATION_ERROR",
                }
                return

            # Build agent configuration
            agent_config = await self.agent_builder_service.build_agent_config(agent_id)
            if not agent_config:
                error_msg = f"Failed to build agent configuration for agent {agent_id}"
                logger.error(error_msg)

                # Publish TaskFailed event
                failed_event = TaskFailed(
                    task_id=task_id,
                    error_message=error_msg,
                    error_code="AGENT_CONFIG_ERROR",
                )
                await self.event_broker.publish(failed_event)

                yield {
                    "event_type": "TaskFailed",
                    "task_id": task_id,
                    "agent_id": str(agent_id),
                    "error_message": error_msg,
                    "error_code": "AGENT_CONFIG_ERROR",
                }
                return

            logger.info(
                f"Starting task {task_id} for agent {agent_config['name']} (ID: {agent_id})"
            )

            # Publish TaskStatusChanged event
            status_changed_event = TaskStatusChanged(
                task_id=task_id,
                old_status=TaskState.SUBMITTED,
                new_status=TaskState.WORKING,
                message=f"Agent {agent_config['name']} started working on task",
            )
            await self.event_broker.publish(status_changed_event)

            # Emit task started event
            yield {
                "event_type": "TaskStatusChanged",
                "task_id": task_id,
                "agent_id": str(agent_id),
                "old_status": "created",
                "new_status": "working",
                "agent_name": agent_config["name"],
            }

            # Create or get session
            app_name = f"agent_{agent_id}_task_{task_id}"
            session = await self.session_service.create_session(
                state={"task_id": task_id, "parameters": task_parameters or {}},
                app_name=app_name,
                user_id=user_id,
            )

            # Configure tools based on agent's tools_config
            tools = []
            tools_config = agent_config.get("tools_config", {})
            if tools_config:
                # Handle MCP servers
                for mcp_server in tools_config.get("mcp_servers", []):
                    logger.info(f"Loading MCP server tool: {mcp_server['name']}")
                    # Here you would implement MCP server tool loading
                    # For now, we'll log the configuration

                # Handle builtin tools
                for builtin_tool in tools_config.get("builtin_tools", []):
                    logger.info(f"Loading builtin tool: {builtin_tool}")
                    # Here you would implement builtin tool loading

                # Handle custom tools
                for custom_tool in tools_config.get("custom_tools", []):
                    logger.info(f"Loading custom tool: {custom_tool}")
                    # Here you would implement custom tool loading

            # Create LLM agent with correct ADK API (no planning parameter)
            # Создаем LiteLLM модель из model_instance
            litellm_model_string, endpoint_url = (
                self._create_litellm_model_from_instance(agent_config["model_instance"])
            )

            litellm_model = LiteLlm(model=litellm_model_string, base_url=endpoint_url)

            llm_agent = LlmAgent(
                name=agent_config["name"],
                model=litellm_model,  # Используем LiteLlm объект
                instruction=agent_config["instruction"],
                tools=tools,
            )

            # -------------------------------------------------------------
            # Integrate Agent-to-Agent communication tool (optional)
            # -------------------------------------------------------------
            if (
                self.agent_communication_service
                and enable_agent_communication is not False
            ):
                llm_agent = (
                    self.agent_communication_service.configure_agent_with_communication(
                        llm_agent, enable_communication=enable_agent_communication
                    )
                )

            # Create runner
            runner = Runner(
                app_name=app_name,
                agent=llm_agent,
                session_service=self.session_service,
            )

            # Create content from query
            content = types.Content(role="user", parts=[types.Part(text=query)])

            # Run the agent and yield events
            response = runner.run_async(
                session_id=session.id,
                user_id=user_id,
                new_message=content,
            )

            # Stream events from the agent runner
            async for event in response:
                # Transform and enrich events with task context
                enriched_event = {
                    "task_id": task_id,
                    "agent_id": str(agent_id),
                    "agent_name": agent_config["name"],
                    "session_id": session.id,
                    "original_event": event,
                }

                # Determine event type based on the event content
                if hasattr(event, "event_type"):
                    enriched_event["event_type"] = event.event_type
                else:
                    # Default event type processing
                    enriched_event["event_type"] = "TaskProgress"

                yield enriched_event

            # Publish TaskCompleted event
            completed_event = TaskCompleted(
                task_id=task_id,
                result={"status": "completed"},
                execution_time=None,  # Could calculate this if needed
            )
            await self.event_broker.publish(completed_event)

            # Emit task completion event
            yield {
                "event_type": "TaskCompleted",
                "task_id": task_id,
                "agent_id": str(agent_id),
                "agent_name": agent_config["name"],
                "session_id": session.id,
                "result": {"status": "completed"},
            }

        except Exception as e:
            logger.error(
                f"Error running agent task {task_id} for agent {agent_id}: {e}",
                exc_info=True,
            )

            # Publish TaskFailed event
            failed_event = TaskFailed(
                task_id=task_id, error_message=str(e), error_code="EXECUTION_ERROR"
            )
            await self.event_broker.publish(failed_event)

            yield {
                "event_type": "TaskFailed",
                "task_id": task_id,
                "agent_id": str(agent_id),
                "error_message": str(e),
                "error_code": "EXECUTION_ERROR",
            }

    async def run_agent(
        self, agent_id: UUID, user_id: str, query: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Legacy method for backward compatibility. Creates a simple task and runs it."""
        task_id = f"simple_task_{agent_id}_{user_id}"
        async for event in self.run_agent_task(agent_id, task_id, user_id, query):
            yield event
