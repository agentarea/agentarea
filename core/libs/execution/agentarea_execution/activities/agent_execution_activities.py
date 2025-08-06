"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: Uses real LLM services for model resolution and execution
"""

# Standard library imports
import logging
from typing import Any
from uuid import UUID

# Third-party imports
# Local imports
from agentarea_agents.application.agent_service import AgentService
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_mcp.application.service import MCPServerInstanceService
from temporalio import activity

from ..agentic import (
    GoalProgressEvaluator,
    LLMModel,
    LLMRequest,
    ToolExecutor,
    ToolManager,
)
from ..interfaces import ActivityDependencies

logger = logging.getLogger(__name__)


def _create_user_context(user_context_data: dict[str, Any]) -> UserContext:
    """Helper function to create UserContext from data dictionary."""
    return UserContext(
        user_id=user_context_data.get("user_id", "system"),
        workspace_id=user_context_data["workspace_id"]
    )


def _create_system_context(workspace_id: str) -> UserContext:
    """Helper function to create system context for background tasks."""
    return UserContext(
        user_id="system",
        workspace_id=workspace_id
    )





def make_agent_activities(dependencies: ActivityDependencies):
    """Factory function to create agent activities with injected dependencies.

    Args:
        dependencies: Basic dependencies needed to create services

    Returns:
        List of activity functions ready for worker registration
    """

    @activity.defn
    async def build_agent_config_activity(
        agent_id: UUID,
        user_context_data: dict[str, Any],  # Pass user context as parameter
        execution_context: dict[str, Any] | None = None,
        step_type: str | None = None,
        override_model: str | None = None,
    ) -> dict[str, Any]:
        """Build agent configuration."""
        # Create fresh session for this activity
        database = get_database()
        async with database.async_session_factory() as session:
            # Reconstruct user context from passed parameters
            user_context = UserContext(
                user_id=user_context_data["user_id"], workspace_id=user_context_data["workspace_id"]
            )

            # Create services with this session
            repository_factory = RepositoryFactory(session, user_context)
            agent_service = AgentService(
                repository_factory=repository_factory, event_broker=dependencies.event_broker
            )

            # Get agent from database
            agent = await agent_service.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # Build configuration dictionary
            agent_config = {
                "id": str(agent.id),
                "name": agent.name,
                "description": agent.description,
                "instruction": agent.instruction,
                "model_id": agent.model_id,
                "tools_config": agent.tools_config or {},
                "events_config": agent.events_config or {},
                "planning": agent.planning,
            }

            if override_model:
                agent_config["model_id"] = override_model
            if execution_context:
                agent_config["execution_context"] = execution_context
            if step_type:
                agent_config["step_type"] = step_type

            return agent_config

    @activity.defn
    async def discover_available_tools_activity(
        agent_id: UUID,
        user_context_data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Discover available tools for an agent."""
        # Create fresh session for this activity
        database = get_database()
        async with database.async_session_factory() as session:
            # Create user context for this activity
            user_context = UserContext(
                user_id=user_context_data["user_id"], workspace_id=user_context_data["workspace_id"]
            )

            # Create services with this session
            repository_factory = RepositoryFactory(session, user_context)
            agent_service = AgentService(
                repository_factory=repository_factory, event_broker=dependencies.event_broker
            )

            mcp_server_instance_service = MCPServerInstanceService(
                repository_factory=repository_factory,
                event_broker=dependencies.event_broker,
                secret_manager=dependencies.secret_manager,
            )

            # Get agent configuration
            agent = await agent_service.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # Use tool manager to discover available tools
            tool_manager = ToolManager()
            all_tools = await tool_manager.discover_available_tools(
                agent_id=agent_id,
                tools_config=agent.tools_config,
                mcp_server_instance_service=mcp_server_instance_service,
            )

            return all_tools

    @activity.defn
    async def call_llm_activity(
        messages: list[dict[str, Any]],
        model_id: str,
        tools: list[dict[str, Any]] | None = None,
        workspace_id: str | None = None,
        user_context_data: dict[str, Any] | None = None,  # Deprecated, use workspace_id
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call LLM with messages and optional tools."""
        try:
            # model_id must be a UUID representing a model instance ID
            try:
                model_uuid = UUID(model_id)
            except ValueError as e:
                raise ValueError(f"Invalid model_id: {model_id}. Must be a valid UUID representing a model instance.") from e

            # Get model instance from database
            async with get_database().async_session_factory() as session:
                # Create context - prefer workspace_id, fallback to user_context_data
                if workspace_id:
                    user_context = _create_system_context(workspace_id)
                elif user_context_data:
                    user_context = _create_user_context(user_context_data)
                else:
                    raise ValueError("Either workspace_id or user_context_data must be provided")

                model_instance_service = ModelInstanceService(
                    repository=ModelInstanceRepository(session, user_context),
                    event_broker=dependencies.event_broker,
                    secret_manager=dependencies.secret_manager,
                )
                model_instance = await model_instance_service.get(model_uuid)
                if not model_instance:
                    raise ValueError(f"Model instance with ID {model_id} not found")

            # Extract required parameters from model instance
            provider_type = model_instance.provider_config.provider_spec.provider_type
            model_name = model_instance.model_spec.model_name
            endpoint_url = getattr(model_instance.model_spec, "endpoint_url", None)

            # Decode API key from secret manager (provider_config.api_key is a secret name/placeholder)
            api_key = None
            api_key_secret_name = getattr(model_instance.provider_config, "api_key", None)
            if api_key_secret_name:
                api_key = await dependencies.secret_manager.get_secret(api_key_secret_name)
            else:
                logger.warning(f"No API key found for model instance {model_instance.id}")

            # Create LLM model with explicit parameters
            llm_model = LLMModel(
                provider_type=provider_type,
                model_name=model_name,
                api_key=api_key,
                endpoint_url=endpoint_url,
            )

            # Create structured request
            request = LLMRequest(
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Get structured response
            response = await llm_model.complete(request)

            # Convert to dict format for backward compatibility with existing workflow code
            result = {
                "content": response.content,
                "role": response.role,
                "cost": response.cost,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            }

            if response.tool_calls:
                result["tool_calls"] = response.tool_calls

            return result

        except Exception as e:
            logger.error(f"LLM call failed: {e!s}")
            raise

    @activity.defn
    async def execute_mcp_tool_activity(
        tool_name: str,
        tool_args: dict[str, Any],
        server_instance_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Execute an MCP tool or built-in completion tool."""
        # Create fresh session for MCP tools if needed
        mcp_server_instance_service = None
        if tool_name != "task_complete":
            database = get_database()
            async with database.async_session_factory() as session:
                # Create services with this session
                repository_factory = RepositoryFactory(session, _create_system_context("system"))
                mcp_server_instance_service = MCPServerInstanceService(
                    repository_factory=repository_factory,
                    event_broker=dependencies.event_broker,
                    secret_manager=dependencies.secret_manager,
                )

        # Use tool executor to handle routing
        tool_executor = ToolExecutor()
        return await tool_executor.execute_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            server_instance_id=server_instance_id,
            mcp_server_instance_service=mcp_server_instance_service,
        )

    @activity.defn
    async def create_execution_plan_activity(
        goal: dict[str, Any],
        available_tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create an execution plan based on the goal and available tools."""
        try:
            # For now, return a simple plan - could be enhanced with actual LLM call
            tool_names = [tool.get("name", "unknown") for tool in available_tools]

            return {
                "plan": f"Execute the task '{goal.get('description', 'Unknown')}' systematically using available tools",
                "estimated_steps": min(max(len(available_tools), 3), 8),  # Between 3-8 steps
                "key_tools": tool_names[:3],  # First 3 tools
                "risk_factors": [
                    "Tool execution failures",
                    "LLM response issues",
                    "External API timeouts",
                ],
            }

        except Exception as e:
            logger.error(f"Failed to create execution plan: {e}")
            return {
                "plan": f"Execute the task '{goal.get('description', 'Unknown')}' step by step",
                "estimated_steps": 5,
                "key_tools": [],
                "risk_factors": ["Planning failed - proceeding with default approach"],
            }

    @activity.defn
    async def evaluate_goal_progress_activity(
        goal: dict[str, Any],
        messages: list[dict[str, Any]],
        current_iteration: int,
    ) -> dict[str, Any]:
        """Evaluate progress toward the goal."""
        evaluator = GoalProgressEvaluator()
        
        # Extract goal information for the new interface
        goal_description = goal.get("description", "")
        success_criteria = goal.get("success_criteria", [])
        
        return await evaluator.evaluate_progress(
            goal_description=goal_description,
            success_criteria=success_criteria,
            conversation_history=messages,
            current_iteration=current_iteration
        )

    @activity.defn
    async def publish_workflow_events_activity(events_json: list[str]) -> bool:
        """Publish workflow events using the EventBroker infrastructure AND store in database."""
        if not events_json:
            return True

        try:
            import json
            from datetime import datetime
            from uuid import uuid4

            from agentarea_common.events.base_events import DomainEvent
            from agentarea_common.events.router import create_event_broker_from_router

            logger.info(f"Publishing {len(events_json)} workflow events via EventBroker and storing in database")

            # Convert RedisRouter to RedisEventBroker for publishing
            # dependencies.event_broker is a RedisRouter, we need RedisEventBroker to publish
            if not hasattr(dependencies.event_broker, "broker"):
                logger.error(
                    f"Event broker {type(dependencies.event_broker)} does not have 'broker' attribute"
                )
                return False

            redis_event_broker = create_event_broker_from_router(dependencies.event_broker)  # type: ignore

            # Get database connection for storing events
            database = get_database()

            for event_json in events_json:
                event = json.loads(event_json)
                task_id = event.get("data", {}).get("task_id", "unknown")

                # Create proper domain event with correct parameters
                domain_event = DomainEvent(
                    event_id=event.get("event_id", str(uuid4())),
                    event_type=f"workflow.{event['event_type']}",  # Prefix for workflow events
                    timestamp=datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                    # All other data goes into the data dict
                    aggregate_id=task_id,
                    aggregate_type="task",
                    original_event_type=event["event_type"],
                    original_timestamp=event["timestamp"],
                    original_data=event["data"],
                )

                # 1. Publish via RedisEventBroker (uses FastStream infrastructure) for real-time SSE
                await redis_event_broker.publish(domain_event)
                logger.debug(f"Published workflow event: {event['event_type']} for task {task_id}")

                # 2. Store in database for persistence
                try:
                    await database.execute(
                        """INSERT INTO task_events (task_id, event_type, timestamp, data, metadata) 
                           VALUES (:task_id, :event_type, :timestamp, :data, :metadata)""",
                        {
                            "task_id": task_id,
                            "event_type": event["event_type"],
                            "timestamp": datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                            "data": event["data"],
                            "metadata": {
                                "execution_id": domain_event.event_id,
                                "aggregate_type": domain_event.aggregate_type,
                                "source": "temporal_workflow"
                            }
                        }
                    )
                    logger.debug(f"Stored workflow event in database: {event['event_type']} for task {task_id}")
                except Exception as db_error:
                    logger.error(f"Failed to store event in database: {db_error}")
                    # Continue with other events even if one fails to store

            return True

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}")
            return False

    # Return all activity functions
    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
    ]
