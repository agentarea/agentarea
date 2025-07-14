"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: LiteLLM for flexible model provider support
"""

import logging
from typing import Any
from uuid import UUID

from temporalio import activity

from ..interfaces import ActivityServicesInterface

logger = logging.getLogger(__name__)


class AgentActivities:
    """Agent activities for Temporal workflows.
    
    Each activity handles a specific piece of logic that workflow can call.
    """

    def __init__(self, services: ActivityServicesInterface):
        self.services = services
        from ..llm_model_resolver import LLMModelResolver
        self.llm_model_resolver = LLMModelResolver()

    @activity.defn
    async def build_agent_config_activity(
        self,
        agent_id: UUID,
        execution_context: dict[str, Any] | None = None,
        step_type: str | None = None,
        override_model: str | None = None,
    ) -> dict[str, Any]:
        """Build agent configuration."""
        try:
            agent_config = await self.services.agent_service.build_agent_config(agent_id)
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found")
            if override_model:
                agent_config["model"] = override_model
            if execution_context:
                agent_config["execution_context"] = execution_context
            if step_type:
                agent_config["step_type"] = step_type
            return agent_config
        except Exception as e:
            logger.error(f"Failed to build agent config for {agent_id}: {e}")
            raise

    @activity.defn
    async def discover_available_tools_activity(
        self,
        agent_id: UUID,
    ) -> list[dict[str, Any]]:
        """Discover available tools for an agent."""
        try:
            agent_config = await self.services.agent_service.build_agent_config(agent_id)
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found")
            mcp_server_ids = agent_config.get("mcp_server_ids", [])
            all_tools: list[dict[str, Any]] = []
            for server_id in mcp_server_ids:
                try:
                    server_tools = await self.services.mcp_service.get_server_tools(UUID(server_id))
                    all_tools.extend(server_tools)
                except Exception as e:
                    logger.warning(f"Failed to get tools from MCP server {server_id}: {e}")
            logger.info(f"Discovered {len(all_tools)} tools for agent {agent_id}")
            return all_tools
        except Exception as e:
            logger.error(f"Failed to discover tools for agent {agent_id}: {e}")
            raise

    @activity.defn
    async def call_llm_activity(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call LLM with messages and optional tools."""
        try:
            # Import LiteLLM only when needed (avoids Temporal sandbox issues)
            import litellm

            # Get the actual LiteLLM model string
            agent_config = {"model": model}  # Simplified for now
            litellm_model = self.llm_model_resolver.get_litellm_model(agent_config)

            # Make actual LiteLLM call
            response = await litellm.acompletion(  # type: ignore
                model=litellm_model,
                messages=messages,
                tools=tools if tools else None,
                temperature=0.7,
                max_tokens=1000,
            )

            # Extract the assistant message from LiteLLM response
            choice = response.choices[0]  # type: ignore
            message = choice.message  # type: ignore

            result = {
                "role": "assistant",
                "content": getattr(message, 'content', '') or "",  # type: ignore
                "finish_reason": getattr(choice, 'finish_reason', 'stop'),  # type: ignore
            }

            # Add tool calls if present
            tool_calls = getattr(message, 'tool_calls', None)  # type: ignore
            if tool_calls:
                result["tool_calls"] = [
                    {
                        "name": getattr(getattr(tc, 'function', None), 'name', ''),
                        "args": getattr(getattr(tc, 'function', None), 'arguments', {}) if hasattr(getattr(tc, 'function', None), 'arguments') else {},
                    }
                    for tc in tool_calls
                ]
            else:
                result["tool_calls"] = []

            return result

        except Exception as e:
            logger.error(f"Error in LLM call: {e}")
            # Return error response
            return {
                "role": "assistant",
                "content": f"Error: {e!s}",
                "tool_calls": [],
                "finish_reason": "error"
            }

    @activity.defn
    async def execute_mcp_tool_activity(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        server_instance_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Execute an MCP tool."""
        try:
            if not server_instance_id:
                available_tools = await self.services.mcp_service.find_alternative_tools(tool_name)
                if not available_tools:
                    raise ValueError(f"No MCP server found with tool: {tool_name}")
                server_instance_id = UUID(available_tools[0]["server_instance_id"])
            result = await self.services.mcp_service.execute_tool(
                server_instance_id=server_instance_id,
                tool_name=tool_name,
                arguments=tool_args,
                timeout_seconds=60,
            )
            return result
        except Exception as e:
            logger.error(f"MCP tool execution failed: {tool_name} - {e}")
            raise

    @activity.defn
    async def check_task_completion_activity(
        self,
        messages: list[dict[str, Any]],
        current_iteration: int,
        max_iterations: int,
    ) -> dict[str, Any]:
        """Check if a task should be considered complete."""
        try:
            # Check iteration limit
            if current_iteration >= max_iterations:
                return {
                    "should_complete": True,
                    "reason": "max_iterations_reached",
                }

            # Check if last assistant message indicates completion
            for message in reversed(messages):
                if message.get("role") == "assistant":
                    content = message.get("content", "").lower()
                    completion_indicators = [
                        "task complete",
                        "finished",
                        "done",
                        "completed successfully",
                        "no further action needed"
                    ]
                    if any(indicator in content for indicator in completion_indicators):
                        return {
                            "should_complete": True,
                            "reason": "completion_indicated",
                        }
                    break

            return {
                "should_complete": False,
                "reason": "continue_execution",
            }
        except Exception as e:
            logger.error(f"Task completion check failed: {e}")
            # Default to continuing on error
            return {
                "should_complete": False,
                "reason": "error_continue",
            }
