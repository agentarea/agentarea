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
import litellm

# Local imports
from agentarea_agents.application.agent_service import AgentService
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.config import get_database
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository
from temporalio import activity

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


async def _create_services_with_session(
    user_context_data: dict[str, Any], dependencies: ActivityDependencies
):
    """Helper function to create database session and common services."""
    database = get_database()
    async with database.async_session_factory() as session:
        user_context = _create_user_context(user_context_data)
        repository_factory = RepositoryFactory(session, user_context)

        agent_service = AgentService(
            repository_factory=repository_factory, event_broker=dependencies.event_broker
        )

        mcp_server_instance_service = MCPServerInstanceService(
            repository_factory=repository_factory,
            event_broker=dependencies.event_broker,
            secret_manager=dependencies.secret_manager,
        )

        return session, user_context, repository_factory, agent_service, mcp_server_instance_service


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

            # Extract MCP server IDs from tools config
            tools_config = agent.tools_config or {}
            mcp_server_ids = tools_config.get("mcp_servers", [])

            all_tools: list[dict[str, Any]] = []

            # Get tools from each configured MCP server
            for server_id in mcp_server_ids:
                server_instance = await mcp_server_instance_service.get(UUID(str(server_id)))
                if server_instance and server_instance.status == "running":
                    # TODO: Implement get_tools method in MCPServerInstanceService
                    # For now, return empty list until MCP tool discovery is implemented
                    logger.warning(f"Tool discovery not yet implemented for MCP server {server_id}")

            logger.info(f"Discovered {len(all_tools)} tools for agent {agent_id}")
            return all_tools

    @activity.defn
    async def call_llm_activity(
        messages: list[dict[str, Any]],
        model_id: str,
        tools: list[dict[str, Any]] | None = None,
        workspace_id: str | None = None,
        user_context_data: dict[str, Any] | None = None,  # Deprecated, use workspace_id
    ) -> dict[str, Any]:
        """Call LLM with messages and optional tools."""
        try:
            # model_id must be a UUID representing a model instance ID
            try:
                model_uuid = UUID(model_id)
            except ValueError:
                raise ValueError(f"Invalid model_id: {model_id}. Must be a valid UUID representing a model instance.")

            # Extract all needed data from model instance before closing session
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

                # Access the model structure
                provider_type = model_instance.provider_config.provider_spec.provider_type
                model_type = model_instance.model_spec.model_name
                api_key = getattr(model_instance.provider_config, "api_key", None)
                endpoint_url = getattr(model_instance.model_spec, "endpoint_url", None)

            # Build litellm parameters with extracted data
            litellm_model = f"{provider_type}/{model_type}"

            litellm_params = {
                "model": litellm_model,
                "messages": messages,
            }
            if api_key:
                litellm_params["api_key"] = api_key
            if endpoint_url:
                url = endpoint_url
                if not url.startswith("http"):
                    url = f"http://{url}"
                litellm_params["base_url"] = url
            if tools:
                litellm_params["tools"] = tools
                litellm_params["tool_choice"] = "auto"
            logger.info(f"Calling LLM with model {litellm_model}")

            # Set base URL for Ollama - use localhost when not in Docker
            if endpoint_url:
                url = endpoint_url
                if not url.startswith("http"):
                    url = f"http://{url}"
                litellm_params["base_url"] = url
            elif provider_type == "ollama_chat":
                # Default Ollama URL - use localhost for local development
                litellm_params["base_url"] = "http://host.docker.internal:11434"

            response = await litellm.acompletion(**litellm_params)
            message = response.choices[0].message
            result = {
                "content": message.content or "",
                "role": message.role,
            }
            if hasattr(message, "tool_calls") and message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                },
            }
                    for tool_call in message.tool_calls
    ]
            # Extract cost information from response usage
            cost = 0.0
            if hasattr(response, "usage") and response.usage:
                usage = response.usage
                # litellm includes cost calculation in some cases
                if hasattr(usage, "completion_tokens_cost"):
                    cost += getattr(usage, "completion_tokens_cost", 0.0)
                if hasattr(usage, "prompt_tokens_cost"):
                    cost += getattr(usage, "prompt_tokens_cost", 0.0)
                # Fallback: calculate cost using token counts if available
                elif hasattr(usage, "total_tokens"):
                    # This is a rough estimate - actual costs vary by model
                    # For production, should use model-specific pricing
                    cost = (
                        getattr(usage, "total_tokens", 0) * 0.00001
                    )  # $0.01 per 1K tokens estimate

            result["cost"] = cost
            result["usage"] = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0)
                if hasattr(response, "usage") and response.usage
                else 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0)
                if hasattr(response, "usage") and response.usage
                else 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0)
                if hasattr(response, "usage") and response.usage
                else 0,
            }

            logger.info(f"LLM call completed successfully, cost: ${cost:.6f}")
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
        """Execute an MCP tool."""
        # Create fresh session for this activity
        database = get_database()
        async with database.async_session_factory() as session:
            # Create services with this session
            mcp_server_repository = MCPServerRepository(session)
            mcp_server_instance_repository = MCPServerInstanceRepository(session)
            mcp_server_instance_service = MCPServerInstanceService(
                repository=mcp_server_instance_repository,
                event_broker=dependencies.event_broker,
                mcp_server_repository=mcp_server_repository,
                secret_manager=dependencies.secret_manager,
            )

            try:
                if server_instance_id:
                    server_instance = await mcp_server_instance_service.get(server_instance_id)
                    if not server_instance:
                        raise ValueError(f"MCP server instance {server_instance_id} not found")
                else:
                    # TODO: Implement tool name to server mapping
                    raise ValueError("Server instance ID is required for tool execution")

                # TODO: Implement execute_tool method in MCPServerInstanceService
                logger.warning(f"Tool execution not yet implemented for tool {tool_name}")

                # Placeholder return
                return {
                    "tool_name": tool_name,
                    "result": f"Tool {tool_name} executed successfully (placeholder)",
                    "success": True,
                }

            except Exception as e:
                logger.error(f"Tool execution failed: {e!s}")
                return {
                    "tool_name": tool_name,
                    "result": f"Tool execution failed: {e!s}",
                    "success": False,
                }

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
        try:
            # Analyze the conversation to determine if goal is achieved
            goal_achieved = False
            final_response = None

            if messages:
                # Check if the last few messages indicate task completion
                recent_messages = messages[-3:]  # Look at last 3 messages

                for message in reversed(recent_messages):
                    if message.get("role") == "assistant":
                        content = message.get("content", "").lower()

                        # Check for completion indicators
                        completion_indicators = [
                            "task completed",
                            "finished",
                            "done",
                            "complete",
                            "successfully",
                            "final answer",
                            "here is the result",
                            "i have completed",
                            "task is finished",
                        ]

                        if any(indicator in content for indicator in completion_indicators):
                            goal_achieved = True
                            final_response = message.get("content", "Task completed")
                            break

                # Also check if we have successful tool executions that might indicate completion
                if not goal_achieved:
                    tool_successes = sum(
                        1
                        for msg in recent_messages
                        if msg.get("role") == "tool"
                        and "error" not in str(msg.get("content", "")).lower()
                    )

                    if (
                        tool_successes >= 2
                    ):  # Multiple successful tool calls might indicate progress
                        # Check if assistant is providing a summary or conclusion
                        for message in reversed(recent_messages):
                            if (
                                message.get("role") == "assistant"
                                and len(message.get("content", "")) > 50
                            ):
                                content = message.get("content", "")
                                if any(
                                    word in content.lower()
                                    for word in ["summary", "result", "conclusion", "completed"]
                                ):
                                    goal_achieved = True
                                    final_response = content
                                    break

            # Evaluate against success criteria if available
            success_criteria_met = []
            if goal.get("success_criteria"):
                # This is a simplified evaluation - could be enhanced with LLM analysis
                for criteria in goal["success_criteria"]:
                    # Simple keyword matching for now
                    criteria_met = any(
                        keyword in " ".join(msg.get("content", "") for msg in messages[-5:]).lower()
                        for keyword in criteria.lower().split()[:3]  # First 3 words of criteria
                    )
                    success_criteria_met.append({"criteria": criteria, "met": criteria_met})

            return {
                "goal_achieved": goal_achieved,
                "final_response": final_response,
                "success_criteria_met": success_criteria_met,
                "progress_indicators": {
                    "message_count": len(messages),
                    "tool_calls": sum(1 for msg in messages if msg.get("role") == "tool"),
                    "assistant_responses": sum(
                        1 for msg in messages if msg.get("role") == "assistant"
                    ),
                    "iteration": current_iteration,
                },
            }

        except Exception as e:
            logger.error(f"Failed to evaluate goal progress: {e}")
            return {
                "goal_achieved": False,
                "final_response": None,
                "success_criteria_met": [],
                "progress_indicators": {"error": str(e)},
            }

    @activity.defn
    async def publish_workflow_events_activity(events_json: list[str]) -> bool:
        """Publish workflow events using the EventBroker infrastructure."""
        if not events_json:
            return True

        try:
            import json
            from datetime import datetime
            from uuid import uuid4

            from agentarea_common.events.base_events import DomainEvent
            from agentarea_common.events.router import create_event_broker_from_router

            logger.info(f"Publishing {len(events_json)} workflow events via EventBroker")

            # Convert RedisRouter to RedisEventBroker for publishing
            # dependencies.event_broker is a RedisRouter, we need RedisEventBroker to publish
            if not hasattr(dependencies.event_broker, "broker"):
                logger.error(
                    f"Event broker {type(dependencies.event_broker)} does not have 'broker' attribute"
                )
                return False

            redis_event_broker = create_event_broker_from_router(dependencies.event_broker)  # type: ignore

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

                # Publish via RedisEventBroker (uses FastStream infrastructure)
                await redis_event_broker.publish(domain_event)
                logger.debug(f"Published workflow event: {event['event_type']} for task {task_id}")

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
