"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: Uses real LLM services for model resolution and execution
"""

import logging
from typing import Any
from uuid import UUID

import litellm
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.config import get_database
from agentarea_llm.application.model_instance_service import ModelInstanceService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository
from temporalio import activity

from ..interfaces import ActivityDependencies

logger = logging.getLogger(__name__)

# Global reference to the call_llm_activity function
# This will be set when make_agent_activities is called
call_llm_activity = None


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
            from agentarea_common.auth.context import UserContext
            user_context = UserContext(
                user_id=user_context_data["user_id"],
                workspace_id=user_context_data["workspace_id"]
            )
            
            # Create services with this session
            from agentarea_common.base import RepositoryFactory
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
            from agentarea_common.auth.context import UserContext
            user_context = UserContext(
                user_id=user_context_data["user_id"],
                workspace_id=user_context_data["workspace_id"]
            )
            
            # Create services with this session
            from agentarea_common.base import RepositoryFactory
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
    async def execute_adk_agent_with_temporal_backbone(
        agent_config: dict[str, Any],
        session_data: dict[str, Any],
        user_message: dict[str, Any],
        run_config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute ADK agent with Temporal backbone enabled.
        
        This activity enables the Temporal backbone and runs an ADK agent,
        ensuring all tool and LLM calls go through Temporal activities.
        """
        # Enable Temporal backbone for all ADK calls
        from ..adk_temporal.interceptors import enable_temporal_backbone
        enable_temporal_backbone()
        
        logger.info(f"Executing ADK agent with Temporal backbone: {agent_config.get('name', 'unknown')}")
        
        # Use the consolidated execute_agent_step function
        events = await execute_agent_step(
            agent_config=agent_config,
            session_data=session_data,
            user_message=user_message,
            run_config=run_config
        )
        
        logger.info(f"ADK agent completed with Temporal backbone - Events: {len(events)}")
        return events

    @activity.defn
    async def call_llm_activity(
        messages: list[dict[str, Any]],
        model_id: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call LLM with messages and optional tools."""
        try:
            # Handle both UUID model instance IDs and direct model names
            provider_type = None
            model_type = None
            api_key = None
            endpoint_url = None

            # Try to treat model_id as a UUID first (model instance ID)
            try:
                model_uuid = UUID(model_id)
                # Extract all needed data from model instance before closing session
                async with get_database().async_session_factory() as session:
                    model_instance_service = ModelInstanceService(
                        repository=ModelInstanceRepository(session),
                        event_broker=dependencies.event_broker,
                        secret_manager=dependencies.secret_manager,
                    )
                    model_instance = await model_instance_service.get(model_uuid)
                    if model_instance:
                        # Access the new model structure
                        provider_type = model_instance.provider_config.provider_spec.provider_type
                        model_type = model_instance.model_spec.model_name
                        api_key = getattr(model_instance.provider_config, "api_key", None)
                        endpoint_url = getattr(model_instance.model_spec, "endpoint_url", None)
                    else:
                        raise ValueError(f"Model instance with ID {model_id} not found")
            except ValueError:
                # Not a UUID, treat as direct model name (e.g., "gpt-4", "claude-3")
                model_type = model_id
                # For direct model names, we'll let litellm handle the provider detection
                # This is common for well-known models like gpt-4, claude-3, etc.

            # Build litellm parameters with extracted data
            if provider_type:
                litellm_model = f"{provider_type}/{model_type}"
            else:
                # Direct model name (e.g., "gpt-4", "claude-3")
                litellm_model = model_type

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
                litellm_params["base_url"] = "http://localhost:11434"

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
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                # litellm includes cost calculation in some cases
                if hasattr(usage, 'completion_tokens_cost'):
                    cost += getattr(usage, 'completion_tokens_cost', 0.0)
                if hasattr(usage, 'prompt_tokens_cost'):
                    cost += getattr(usage, 'prompt_tokens_cost', 0.0)
                # Fallback: calculate cost using token counts if available
                elif hasattr(usage, 'total_tokens'):
                    # This is a rough estimate - actual costs vary by model
                    # For production, should use model-specific pricing
                    cost = getattr(usage, 'total_tokens', 0) * 0.00001  # $0.01 per 1K tokens estimate

            result["cost"] = cost
            result["usage"] = {
                "prompt_tokens": getattr(response.usage, 'prompt_tokens', 0) if hasattr(response, 'usage') and response.usage else 0,
                "completion_tokens": getattr(response.usage, 'completion_tokens', 0) if hasattr(response, 'usage') and response.usage else 0,
                "total_tokens": getattr(response.usage, 'total_tokens', 0) if hasattr(response, 'usage') and response.usage else 0,
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

    # @activity.defn
    # async def check_task_completion_activity(
    #     messages: list[dict[str, Any]],
    #     current_iteration: int,
    #     max_iterations: int,
    # ) -> dict[str, Any]:
    #     """Check if the task is complete based on the conversation."""
    #     # This activity doesn't need database access, just logic

    #     # Simple completion check logic
    #     if current_iteration >= max_iterations:
    #         return {"is_complete": True, "reason": f"Maximum iterations ({max_iterations}) reached"}

    #     # Check if the last message indicates completion
    #     if messages:
    #         last_message = messages[-1]
    #         content = last_message.get("content", "").lower()

    #         # Simple heuristics for completion
    #         completion_indicators = [
    #             "task completed",
    #             "finished",
    #             "done",
    #             "completed successfully",
    #             "task is complete",
    #         ]

    #         if any(indicator in content for indicator in completion_indicators):
    #             return {"is_complete": True, "reason": "Task completion detected in response"}

    #     return {
    #         "is_complete": False,
    #         "reason": f"Task not complete, iteration {current_iteration}/{max_iterations}",
    #     }

    @activity.defn
    async def create_execution_plan_activity(
        goal: dict[str, Any],
        available_tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Create an execution plan based on the goal and available tools."""
        try:
            # Use LLM to create an execution plan
            planning_messages = [
                {
                    "role": "system",
                    "content": f"""You are an AI planning assistant. Create a step-by-step execution plan to achieve the given goal.

GOAL: {goal.get("description", "No description provided")}

SUCCESS CRITERIA:
{chr(10).join(f"- {criteria}" for criteria in goal.get("success_criteria", []))}

AVAILABLE TOOLS:
{chr(10).join(f"- {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}" for tool in available_tools)}

Create a concrete plan with estimated steps. Return your response as a JSON object with:
- "plan": string describing the step-by-step approach
- "estimated_steps": integer number of expected steps
- "key_tools": list of tool names that will likely be needed
- "risk_factors": list of potential challenges or risks""",
                },
                {
                    "role": "user",
                    "content": f"Create an execution plan for: {goal.get('description', 'Unknown goal')}",
                },
            ]

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
            if not hasattr(dependencies.event_broker, 'broker'):
                logger.error(f"Event broker {type(dependencies.event_broker)} does not have 'broker' attribute")
                return False

            redis_event_broker = create_event_broker_from_router(dependencies.event_broker)  # type: ignore

            for event_json in events_json:
                event = json.loads(event_json)
                task_id = event.get('data', {}).get('task_id', 'unknown')

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
                    original_data=event["data"]
                )

                # Publish via RedisEventBroker (uses FastStream infrastructure)
                await redis_event_broker.publish(domain_event)
                logger.debug(f"Published workflow event: {event['event_type']} for task {task_id}")

            return True

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}")
            return False

    # ===== ADK-SPECIFIC ACTIVITIES =====
    # These activities work directly with the ADK framework
    
    @activity.defn
    async def validate_agent_configuration(
        agent_config: dict[str, Any]
    ) -> bool:
        """Validate ADK agent configuration.
        
        Args:
            agent_config: Dictionary containing agent configuration
            
        Returns:
            True if configuration is valid, False otherwise
            
        Raises:
            ValueError: If configuration is invalid
        """
        from ..adk_temporal.utils.agent_builder import validate_agent_config
        
        try:
            activity_info = activity.info()
            logger.info(f"Validating agent configuration - Activity: {activity_info.activity_type}")
        except RuntimeError:
            logger.info("Validating agent configuration - Direct mode")
        
        if not validate_agent_config(agent_config):
            raise ValueError("Invalid agent configuration")
        
        return True

    @activity.defn
    async def create_agent_runner(
        agent_config: dict[str, Any],
        session_data: dict[str, Any]
    ) -> None:
        """Create ADK runner with service bridges.
        
        Args:
            agent_config: Dictionary containing agent configuration
            session_data: Dictionary containing session information
            
        Returns:
            None
            
        Raises:
            Exception: If runner creation fails
        """
        from ..adk_temporal.services.adk_service_factory import create_adk_runner
        
        try:
            activity_info = activity.info()
            logger.info(f"Creating agent runner - Activity: {activity_info.activity_type}")
        except RuntimeError:
            logger.info("Creating agent runner - Direct mode")
        
        # Create ADK runner with service bridges
        runner = create_adk_runner(agent_config, session_data)
        logger.info("Successfully created ADK runner")

    @activity.defn
    async def execute_agent_step(
        agent_config: dict[str, Any],
        session_data: dict[str, Any],
        user_message: dict[str, Any],
        run_config: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a single step of ADK agent execution with Temporal backbone.
        
        Args:
            agent_config: Dictionary containing agent configuration
            session_data: Dictionary containing session information
            user_message: Dictionary containing user message content
            run_config: Optional run configuration
            
        Returns:
            List of serialized event dictionaries from this step
            
        Raises:
            Exception: If agent execution fails
        """
        from ..adk_temporal.services.adk_service_factory import create_adk_runner
        from ..adk_temporal.utils.event_serializer import EventSerializer
        from ..ag.adk.agents.run_config import RunConfig
        from google.genai import types
        
        try:
            activity_info = activity.info()
            logger.info(f"Executing agent step - Activity: {activity_info.activity_type}")
        except RuntimeError:
            logger.info("Executing agent step - Direct mode")
        
        # Create ADK runner with Temporal backbone enabled
        runner = create_adk_runner(
            agent_config, 
            session_data, 
            use_temporal_services=False,  # Keep session services simple
            use_temporal_backbone=True    # Enable Temporal for tool/LLM calls
        )
        
        # Convert user message to ADK Content
        user_content = _dict_to_adk_content(user_message)
        
        # Prepare run config - always provide a default
        adk_run_config = RunConfig(**run_config) if run_config else RunConfig()
        
        # Execute agent and collect events
        events = []
        event_count = 0
        
        logger.info(f"Starting Temporal-backed agent step for agent: {agent_config.get('name', 'unknown')}")
        
        # Heartbeat to prevent timeout during long-running operations
        activity.heartbeat("Executing ADK agent step with Temporal backbone...")
        
        async for event in runner.run_async(
            user_id=session_data.get("user_id", "default"),
            session_id=session_data.get("session_id", "default"),
            new_message=user_content,
            run_config=adk_run_config
        ):
            event_count += 1
            
            # Serialize event for Temporal storage
            event_dict = EventSerializer.event_to_dict(event)
            events.append(event_dict)
            
            # Log progress periodically
            if event_count % 5 == 0:
                logger.info(f"Processed {event_count} events")
                # Send heartbeat every 5 events
                activity.heartbeat(f"Processed {event_count} events")
            
            # Check if this is the final response
            if event.is_final_response():
                logger.info(f"Agent step completed with final response after {event_count} events")
                break
                
        # Final heartbeat before completion
        activity.heartbeat("Finalizing agent step...")
        
        logger.info(f"ADK agent step completed with Temporal backbone - Events: {len(events)}")
        return events

    @activity.defn
    async def validate_adk_agent_config(agent_config: dict[str, Any]) -> dict[str, Any]:
        """Validate ADK agent configuration with detailed results.
        
        Args:
            agent_config: Dictionary containing agent configuration
            
        Returns:
            Dictionary with validation results:
            - valid: boolean indicating if config is valid
            - errors: list of validation error messages
            - warnings: list of warning messages
        """
        from ..adk_temporal.utils.agent_builder import validate_agent_config, build_adk_agent_from_config
        
        logger.info("Validating ADK agent configuration")
        
        errors = []
        warnings = []
        
        # Basic validation
        if not validate_agent_config(agent_config):
            errors.append("Agent configuration failed basic validation")
        
        # Check required fields
        if not agent_config.get("name"):
            errors.append("Agent name is required")
        elif not isinstance(agent_config["name"], str):
            errors.append("Agent name must be a string")
        
        # Check model
        model = agent_config.get("model")
        if not model:
            warnings.append("No model specified, will use default")
        elif not isinstance(model, str):
            errors.append("Model must be a string")
        
        # Check tools
        tools = agent_config.get("tools", [])
        if tools and not isinstance(tools, list):
            errors.append("Tools must be a list")
        else:
            for i, tool_config in enumerate(tools):
                if not isinstance(tool_config, dict):
                    errors.append(f"Tool {i} must be a dictionary")
                elif not tool_config.get("name"):
                    errors.append(f"Tool {i} missing required 'name' field")
        
        # Try to build agent to catch construction errors
        if not errors:
            try:
                agent = build_adk_agent_from_config(agent_config)
                if not agent:
                    errors.append("Failed to build agent from configuration")
            except Exception as e:
                errors.append(f"Agent construction failed: {str(e)}")
        
        result = {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
        
        logger.info(f"Configuration validation completed - Valid: {result['valid']}, Errors: {len(errors)}, Warnings: {len(warnings)}")
        return result

    # Helper function for ADK activities
    def _dict_to_adk_content(message_dict: dict[str, Any]):
        """Convert message dictionary to ADK Content object.
        
        Args:
            message_dict: Dictionary containing message content
            
        Returns:
            ADK Content object
        """
        from google.genai import types
        from ..adk_temporal.utils.event_serializer import EventSerializer
        
        content_data = message_dict.get("content", {})
        
        # Handle different content formats
        if isinstance(content_data, str):
            # Simple text content
            return types.Content(parts=[types.Part(text=content_data)])
        elif isinstance(content_data, dict):
            # Structured content - try to deserialize
            deserialized = EventSerializer.deserialize_content(content_data)
            return deserialized if deserialized is not None else types.Content(parts=[types.Part(text=str(content_data))])
        else:
            # Fallback to string representation
            return types.Content(parts=[types.Part(text=str(content_data))])

    # Make call_llm_activity available at module level for imports
    import sys
    current_module = sys.modules[__name__]
    setattr(current_module, 'call_llm_activity', call_llm_activity)

    # Return all activity functions
    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        execute_adk_agent_with_temporal_backbone,
        call_llm_activity,
        execute_mcp_tool_activity,
        # check_task_completion_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
        # ADK-specific activities
        validate_agent_configuration,
        create_agent_runner,
        execute_agent_step,
        validate_adk_agent_config,
    ]
