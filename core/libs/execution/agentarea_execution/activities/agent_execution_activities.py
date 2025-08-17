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
import os
from typing import Any
from uuid import UUID

from agentarea_agents_sdk import (
    GoalProgressEvaluator,
    LLMModel,
    LLMRequest,
    ToolExecutor,
    ToolManager,
)

# Local imports
from agentarea_common.auth.context import UserContext

# Third-party imports
from temporalio import activity

from ..interfaces import ActivityDependencies
from .event_publisher import create_event_publisher, publish_enriched_llm_error_event

logger = logging.getLogger(__name__)


def make_agent_activities(dependencies: ActivityDependencies):
    """Factory function to create agent activities with injected dependencies.

    Args:
        dependencies: Basic dependencies needed to create services

    Returns:
        List of activity functions ready for worker registration
    """
    from .dependencies import (
        ActivityContext,
        ActivityServiceContainer,
        create_system_context,
        create_user_context,
    )

    # Create service container
    container = ActivityServiceContainer(dependencies)

    @activity.defn
    async def build_agent_config_activity(
        agent_id: UUID,
        user_context_data: dict[str, Any],
        execution_context: dict[str, Any] | None = None,
        step_type: str | None = None,
        override_model: str | None = None,
    ) -> dict[str, Any]:
        """Build agent configuration."""
        user_context = create_user_context(user_context_data)

        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()

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
        user_context = create_user_context(user_context_data)

        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()

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
        task_id: str | None = None,  # For event publishing
        agent_id: str | None = None,  # For event publishing
        execution_id: str | None = None,  # For event publishing
    ) -> dict[str, Any]:
        """Call LLM with messages and optional tools using streaming.
        
        Note: Messages should be normalized to exclude None values to match agent SDK format.
        Use MessageBuilder.normalize_message_dict() in workflow to ensure consistency.
        """
        try:
            # model_id must be a UUID representing a model instance ID
            try:
                model_uuid = UUID(model_id)
            except ValueError as e:
                raise ValueError(f"Invalid model_id: {model_id}. Must be a valid UUID representing a model instance.") from e

            # Create context - prefer workspace_id, fallback to user_context_data
            if workspace_id:
                user_context = create_system_context(workspace_id)
            elif user_context_data:
                user_context = create_user_context(user_context_data)
            else:
                raise ValueError("Either workspace_id or user_context_data must be provided")

            # Get model instance from database using clean DI
            async with ActivityContext(container, user_context) as ctx:
                model_instance_service = await ctx.get_model_instance_service()
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

            # TODO: replace with proper config class
            docker_host = os.environ.get("LLM_DOCKER_HOST")
            if docker_host and provider_type == "ollama_chat":
                endpoint_url = f"http://{docker_host}:11434"

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

            # Use streaming with ainvoke_stream and publish events
            complete_content = ""
            complete_tool_calls = None
            final_usage = None
            final_cost = 0.0
            chunk_index = 0

            # Create event publisher if we have task context
            event_publisher = None
            if task_id:
                event_publisher = create_event_publisher(dependencies.event_broker, task_id)

            # Stream the response and collect chunks
            async for chunk_response in llm_model.ainvoke_stream(request):
                # Accumulate content
                if chunk_response.content:
                    complete_content += chunk_response.content

                    # Publish chunk event
                    if event_publisher:
                        await event_publisher(chunk_response.content, chunk_index, False)
                        chunk_index += 1

                # Update tool calls (they come complete in each chunk)
                if chunk_response.tool_calls:
                    complete_tool_calls = chunk_response.tool_calls

                # Update usage and cost information
                if chunk_response.usage:
                    final_usage = chunk_response.usage
                if chunk_response.cost:
                    final_cost = chunk_response.cost

            # Publish final chunk event
            if event_publisher:
                await event_publisher("", chunk_index, True)

            # Create final response
            from agentarea_agents_sdk.models.llm_model import LLMResponse
            final_response = LLMResponse(
                content=complete_content,
                role="assistant",
                tool_calls=complete_tool_calls,
                cost=final_cost,
                usage=final_usage,
            )

            # Convert SDK LLMResponse to dict format expected by workflow
            result = {
                "role": final_response.role,
                "content": final_response.content,
                "tool_calls": final_response.tool_calls,
                "cost": final_response.cost,
                "usage": final_response.usage.__dict__ if final_response.usage else None,
                # Include reasoning text for debugging (workflow can use this if needed)
                # "reasoning_text": reasoning_text
            }

            return result

        except Exception as e:
            # Enhanced error handling - create enriched error event if we have event context
            if task_id and agent_id and dependencies.event_broker:
                await publish_enriched_llm_error_event(
                    error=e,
                    task_id=task_id,
                    agent_id=agent_id,
                    execution_id=execution_id or "",
                    model_id=model_id,
                    provider_type=provider_type if 'provider_type' in locals() else None,
                    event_broker=dependencies.event_broker
                )

            # Legacy error handling for backward compatibility
            error_type = type(e).__name__
            error_message = str(e)

            # Simplified error raising - workflow will handle enriched events
            logger.error(f"LLM call failed: {error_message}")
            from temporalio.exceptions import ApplicationError

            # Import error checking functions from event_publisher
            from .event_publisher import _is_non_retryable_error

            raise ApplicationError(
                f"LLM call failed: {error_message}",
                type=error_type,
                non_retryable=_is_non_retryable_error(e)
            ) from e

    @activity.defn
    async def execute_mcp_tool_activity(
        tool_name: str,
        tool_args: dict[str, Any],
        server_instance_id: UUID | None = None,
        workspace_id: str = "system",
        tools_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute an MCP tool or built-in tool."""
        user_context = create_system_context(workspace_id)
        async with ActivityContext(container, user_context) as ctx:
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()

            # Create tool executor with properly configured builtin tools
            from agentarea_agents_sdk.tools.builtin_tools_loader import create_builtin_tool_instance
            from agentarea_agents_sdk.tools.decorator_tool import Toolset, ToolsetAdapter

            tool_executor = ToolExecutor()

            # Register builtin tools from configuration
            if tools_config and tools_config.get("builtin_tools"):
                for tool_config in tools_config["builtin_tools"]:
                    if isinstance(tool_config, dict):
                        builtin_tool_name = tool_config["tool_name"]
                        # Extract method configuration
                        disabled_methods = tool_config.get("disabled_methods", {})

                        # Convert disabled_methods to constructor arguments
                        toolset_methods = dict.fromkeys(disabled_methods.keys(), False) if disabled_methods else {}
                    else:
                        builtin_tool_name = tool_config
                        toolset_methods = {}

                    # Create and register the builtin tool instance
                    tool_instance = create_builtin_tool_instance(builtin_tool_name, toolset_methods)
                    if tool_instance:
                        # Check if tool is a Toolset - if so, wrap it in adapter for compatibility
                        if isinstance(tool_instance, Toolset):
                            tool_instance = ToolsetAdapter(tool_instance)

                        tool_executor.register_tool(tool_instance)
                        logger.info(f"Registered builtin tool for execution: {builtin_tool_name}")
                    else:
                        logger.warning(f"Unknown builtin tool requested: {builtin_tool_name}")

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
        try:
            import json
            from datetime import datetime
            from uuid import uuid4

            from agentarea_common.events.base_events import DomainEvent
            from agentarea_common.events.router import create_event_broker_from_router

            from ..handlers import handle_llm_error_event

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

                # # Check if this is an A2A-originated task by looking at the event data
                # event_data = event.get("data", {})
                # task_metadata = event_data.get("metadata", {})
                # is_a2a_task = task_metadata.get("source") == "a2a"

                # # Enhance event data with A2A monitoring information if this is an A2A task
                # enhanced_event_data = event["data"].copy()
                # if is_a2a_task:
                #     from datetime import UTC
                #     enhanced_event_data["a2a_metadata"] = {
                #         "is_a2a_originated": True,
                #         "a2a_method": task_metadata.get("a2a_method"),
                #         "a2a_request_id": task_metadata.get("a2a_request_id"),
                #         "auth_method": task_metadata.get("auth_method"),
                #         "authenticated": task_metadata.get("authenticated"),
                #         "monitoring_metadata": task_metadata.get("monitoring", {}),
                #         "event_enhanced_timestamp": datetime.now(UTC).isoformat()
                #     }

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
                    original_data=event["data"],  # Include the original event data for tool calls
                )

                # 1. Publish via RedisEventBroker (uses FastStream infrastructure) for real-time SSE
                await redis_event_broker.publish(domain_event)
                logger.debug(f"Published workflow event: {event['event_type']} for task {task_id}")

                # 2. Store event in database using proper service layer
                try:
                    workspace_id = event["data"].get("workspace_id", "default")
                    user_context = UserContext(user_id="workflow", workspace_id=workspace_id)

                    async with ActivityContext(container, user_context) as ctx:
                        task_event_service = await ctx.get_task_event_service()

                        # Create event using service
                        await task_event_service.create_workflow_event(
                            task_id=UUID(task_id),
                            event_type=event["event_type"],
                            data=event["data"],
                            workspace_id=workspace_id,
                            created_by="workflow"
                        )

                        # Commit is handled by the service
                        logger.debug(f"Stored event using service: {event['event_type']} for task {task_id}")

                except Exception as db_error:
                    logger.error(f"Failed to store event using service: {db_error}")
                    # Continue processing other events even if one fails

                # 3. Handle LLM error events locally for immediate action
                if event["event_type"].startswith("LLM") and "Failed" in event["event_type"]:
                    try:
                        await handle_llm_error_event(domain_event)
                    except Exception as handler_error:
                        logger.error(f"Failed to handle LLM error event: {handler_error}")

            return True

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}")
            raise e

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
