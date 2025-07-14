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
from agentarea_llm.application.service import LLMModelInstanceService
from agentarea_llm.infrastructure.llm_model_instance_repository import LLMModelInstanceRepository
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository, MCPServerRepository
from temporalio import activity

from ..interfaces import ActivityDependencies

logger = logging.getLogger(__name__)


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
        execution_context: dict[str, Any] | None = None,
        step_type: str | None = None,
        override_model: str | None = None,
    ) -> dict[str, Any]:
        """Build agent configuration."""
        # Create fresh session for this activity
        database = get_database()
        async with database.async_session_factory() as session:
            # Create services with this session
            agent_repository = AgentRepository(session)
            agent_service = AgentService(
                repository=agent_repository,
                event_broker=dependencies.event_broker
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
    ) -> list[dict[str, Any]]:
        """Discover available tools for an agent."""
        # Create fresh session for this activity
        database = get_database()
        async with database.async_session_factory() as session:
            # Create services with this session
            agent_repository = AgentRepository(session)
            agent_service = AgentService(
                repository=agent_repository,
                event_broker=dependencies.event_broker
            )

            mcp_server_repository = MCPServerRepository(session)
            mcp_server_instance_repository = MCPServerInstanceRepository(session)
            mcp_server_instance_service = MCPServerInstanceService(
                repository=mcp_server_instance_repository,
                event_broker=dependencies.event_broker,
                mcp_server_repository=mcp_server_repository,
                secret_manager=dependencies.secret_manager
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
    ) -> dict[str, Any]:
        """Call LLM with messages and optional tools."""
        # Create fresh session for this activity
        database = get_database()
        async with database.async_session_factory() as session:
            # Create services with this session
            llm_model_instance_repository = LLMModelInstanceRepository(session)
            llm_model_instance_service = LLMModelInstanceService(
                repository=llm_model_instance_repository,
                event_broker=dependencies.event_broker,
                secret_manager=dependencies.secret_manager
            )

            try:
                # Get model instance
                model_instance = await llm_model_instance_service.get(UUID(model_id))
                if not model_instance:
                    raise ValueError(f"Model instance {model_id} not found")

                # Construct proper model string for LiteLLM
                # For legacy models, we need to construct: provider_type/model_type
                provider_type = model_instance.model.provider.provider_type
                model_type = model_instance.model.model_type

                # Construct LiteLLM model string
                litellm_model = f"{provider_type}/{model_type}"

                # Prepare LiteLLM call parameters
                litellm_params = {
                    "model": litellm_model,
                    "messages": messages,
                }

                # Add API key if available
                if hasattr(model_instance, 'api_key') and model_instance.api_key:
                    litellm_params["api_key"] = model_instance.api_key

                # Add endpoint URL if available
                if model_instance.model.endpoint_url:
                    url = model_instance.model.endpoint_url
                    if not url.startswith("http"):
                        url = f"http://{url}"
                    litellm_params["base_url"] = url

                # Add tools if provided
                if tools:
                    litellm_params["tools"] = tools
                    litellm_params["tool_choice"] = "auto"

                # Make LLM call
                logger.info(f"Calling LLM with model {litellm_model}")


                # TODO: it's very dirty hack that we need to remove
                litellm_params["base_url"] = "http://host.docker.internal:11434"
                response = await litellm.acompletion(**litellm_params)

                # Extract response content
                message = response.choices[0].message
                result = {
                    "content": message.content or "",
                    "role": message.role,
                }

                # Handle tool calls if present
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    result["tool_calls"] = [
                        {
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            }
                        }
                        for tool_call in message.tool_calls
                    ]

                logger.info("LLM call completed successfully")
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
                secret_manager=dependencies.secret_manager
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
                    "success": True
                }

            except Exception as e:
                logger.error(f"Tool execution failed: {e!s}")
                return {
                    "tool_name": tool_name,
                    "result": f"Tool execution failed: {e!s}",
                    "success": False
                }

    @activity.defn
    async def check_task_completion_activity(
        messages: list[dict[str, Any]],
        current_iteration: int,
        max_iterations: int,
    ) -> dict[str, Any]:
        """Check if the task is complete based on the conversation."""
        # This activity doesn't need database access, just logic

        # Simple completion check logic
        if current_iteration >= max_iterations:
            return {
                "is_complete": True,
                "reason": f"Maximum iterations ({max_iterations}) reached"
            }

        # Check if the last message indicates completion
        if messages:
            last_message = messages[-1]
            content = last_message.get("content", "").lower()

            # Simple heuristics for completion
            completion_indicators = [
                "task completed",
                "finished",
                "done",
                "completed successfully",
                "task is complete"
            ]

            if any(indicator in content for indicator in completion_indicators):
                return {
                    "is_complete": True,
                    "reason": "Task completion detected in response"
                }

        return {
            "is_complete": False,
            "reason": f"Task not complete, iteration {current_iteration}/{max_iterations}"
        }

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

GOAL: {goal.get('description', 'No description provided')}

SUCCESS CRITERIA:
{chr(10).join(f"- {criteria}" for criteria in goal.get('success_criteria', []))}

AVAILABLE TOOLS:
{chr(10).join(f"- {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}" for tool in available_tools)}

Create a concrete plan with estimated steps. Return your response as a JSON object with:
- "plan": string describing the step-by-step approach
- "estimated_steps": integer number of expected steps
- "key_tools": list of tool names that will likely be needed
- "risk_factors": list of potential challenges or risks"""
                },
                {
                    "role": "user", 
                    "content": f"Create an execution plan for: {goal.get('description', 'Unknown goal')}"
                }
            ]
            
            # For now, return a simple plan - could be enhanced with actual LLM call
            tool_names = [tool.get("name", "unknown") for tool in available_tools]
            
            return {
                "plan": f"Execute the task '{goal.get('description', 'Unknown')}' systematically using available tools",
                "estimated_steps": min(max(len(available_tools), 3), 8),  # Between 3-8 steps
                "key_tools": tool_names[:3],  # First 3 tools
                "risk_factors": ["Tool execution failures", "LLM response issues", "External API timeouts"]
            }
            
        except Exception as e:
            logger.error(f"Failed to create execution plan: {e}")
            return {
                "plan": f"Execute the task '{goal.get('description', 'Unknown')}' step by step",
                "estimated_steps": 5,
                "key_tools": [],
                "risk_factors": ["Planning failed - proceeding with default approach"]
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
                            "task is finished"
                        ]
                        
                        if any(indicator in content for indicator in completion_indicators):
                            goal_achieved = True
                            final_response = message.get("content", "Task completed")
                            break
                
                # Also check if we have successful tool executions that might indicate completion
                if not goal_achieved:
                    tool_successes = sum(1 for msg in recent_messages 
                                       if msg.get("role") == "tool" and "error" not in str(msg.get("content", "")).lower())
                    
                    if tool_successes >= 2:  # Multiple successful tool calls might indicate progress
                        # Check if assistant is providing a summary or conclusion
                        for message in reversed(recent_messages):
                            if message.get("role") == "assistant" and len(message.get("content", "")) > 50:
                                content = message.get("content", "")
                                if any(word in content.lower() for word in ["summary", "result", "conclusion", "completed"]):
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
                    success_criteria_met.append({
                        "criteria": criteria,
                        "met": criteria_met
                    })
            
            return {
                "goal_achieved": goal_achieved,
                "final_response": final_response,
                "success_criteria_met": success_criteria_met,
                "progress_indicators": {
                    "message_count": len(messages),
                    "tool_calls": sum(1 for msg in messages if msg.get("role") == "tool"),
                    "assistant_responses": sum(1 for msg in messages if msg.get("role") == "assistant"),
                    "iteration": current_iteration
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to evaluate goal progress: {e}")
            return {
                "goal_achieved": False,
                "final_response": None,
                "success_criteria_met": [],
                "progress_indicators": {"error": str(e)}
            }

    # Return all activity functions
    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        check_task_completion_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
    ]
