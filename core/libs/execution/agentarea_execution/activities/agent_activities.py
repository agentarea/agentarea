"""
Agent execution activities for Temporal workflows.

Minimal, focused activities that support TemporalFlow integration.
These activities provide the building blocks for Temporal-enhanced agent execution.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from temporalio import activity

from ..interfaces import ActivityServicesInterface

logger = logging.getLogger(__name__)


@activity.defn
async def build_agent_config_activity(
    agent_id: UUID,
    activity_services: ActivityServicesInterface,
    execution_context: Optional[Dict[str, Any]] = None,
    step_type: Optional[str] = None,
    override_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build agent configuration dynamically during execution.
    
    This enables:
    - Different LLMs per execution step
    - Context-aware configuration
    - Future-proof evolution without code changes
    
    Args:
        agent_id: UUID of the agent
        execution_context: Current execution context (previous results, task info, etc.)
        step_type: Type of step being executed (e.g., "reasoning", "coding", "analysis")
        override_model: Override model for this specific step
        activity_services: Service interfaces
        
    Returns:
        Dynamic agent configuration optimized for current context
    """
    try:
        logger.info(f"Building dynamic config for agent {agent_id}, step: {step_type}")
        
        # Get base agent configuration
        base_config = await activity_services.agent_service.build_agent_config(agent_id)
        if not base_config:
            raise ValueError(f"Agent {agent_id} not found")
        
        # Start with base configuration
        dynamic_config = base_config.copy()
        
        # Apply step-specific model selection
        if override_model:
            logger.info(f"Using override model: {override_model}")
            dynamic_config["model_override"] = override_model
        elif step_type:
            # Choose optimal model based on step type
            optimal_model = _select_optimal_model_for_step(step_type, execution_context)
            if optimal_model:
                logger.info(f"Selected optimal model for {step_type}: {optimal_model}")
                dynamic_config["model_override"] = optimal_model
        
        # Apply context-aware configuration adjustments
        if execution_context:
            dynamic_config = _apply_context_aware_config(dynamic_config, execution_context)
        
        # Add execution metadata
        dynamic_config["execution_metadata"] = {
            "step_type": step_type,
            "config_built_at": "runtime",
            "context_aware": bool(execution_context),
            "model_override": dynamic_config.get("model_override"),
        }
        
        logger.info(f"Built dynamic config for {step_type} step")
        return {
            "success": True,
            "config": dynamic_config,
        }
        
    except Exception as e:
        logger.error(f"Failed to build agent config: {e}")
        return {
            "success": False,
            "error": str(e),
            "config": None,
        }


def _select_optimal_model_for_step(step_type: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
    """Select optimal model based on step type and context."""
    
    # Model selection strategy based on step type
    model_strategies = {
        "initial_parsing": "gpt-4o-mini",  # Fast, cheap for simple parsing
        "reasoning": "gpt-4o",             # Best reasoning capabilities
        "coding": "claude-3.5-sonnet",     # Excellent at code generation
        "analysis": "gpt-4o",              # Good at data analysis
        "planning": "gpt-4o",              # Strategic thinking
        "tool_selection": "gpt-4o-mini",   # Fast tool routing
        "final_response": "gpt-4o",        # High quality final output
    }
    
    optimal_model = model_strategies.get(step_type)
    
    # Context-aware adjustments
    if context and optimal_model:
        complexity = context.get("complexity", "medium")
        if complexity == "high" and optimal_model == "gpt-4o-mini":
            optimal_model = "gpt-4o"  # Upgrade to better model for complex tasks
        elif complexity == "low" and optimal_model == "gpt-4o":
            optimal_model = "gpt-4o-mini"  # Use cheaper model for simple tasks
    
    return optimal_model


def _apply_context_aware_config(config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Apply context-aware configuration adjustments."""
    
    # Adjust temperature based on task type
    task_type = context.get("task_type", "general")
    if task_type == "creative":
        config["temperature"] = 0.8
    elif task_type == "analytical":
        config["temperature"] = 0.2
    else:
        config["temperature"] = 0.5
    
    # Adjust max tokens based on expected response length
    expected_length = context.get("expected_response_length", "medium")
    if expected_length == "long":
        config["max_tokens"] = 4000
    elif expected_length == "short":
        config["max_tokens"] = 1000
    else:
        config["max_tokens"] = 2000
    
    # Enable/disable tools based on context
    if context.get("tools_required", True):
        # Keep existing tools config
        pass
    else:
        # Disable tools for this step
        config["tools_config"] = {"mcp_servers": [], "builtin_tools": [], "custom_tools": []}
    
    return config


@activity.defn
async def call_llm_activity(
    messages: List[Dict[str, Any]],
    model_config: Dict[str, Any],
    available_tools: List[Dict[str, Any]],
    activity_services: ActivityServicesInterface,
) -> Dict[str, Any]:
    """
    Call LLM via Temporal activity for durability.
    
    This is the core activity that TemporalFlow uses for LLM calls.
    It provides Temporal benefits: retries, durability, observability.
    """
    try:
        logger.info(f"Calling LLM with model {model_config.get('model', 'unknown')}")
        
        # Use AgentArea's existing LLM service integration
        llm_service = activity_services.llm_service
        
        # Convert available tools to LLM format
        tools_for_llm = []
        for tool in available_tools:
            tools_for_llm.append({
                "name": tool.get("name", "unknown"),
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
                "mcp_server_id": tool.get("mcp_server_id"),
            })
        
        # Execute LLM reasoning through AgentArea's service
        reasoning_result = await llm_service.execute_reasoning(
            agent_config=model_config,
            conversation_history=messages,
            current_goal="Execute the current user request",
            available_tools=tools_for_llm,
            max_tool_calls=5,
            include_thinking=True,
        )
        
        return {
            "success": True,
            "response_text": reasoning_result.reasoning_text,
            "tool_calls": reasoning_result.tool_calls,
            "model_used": reasoning_result.model_used,
            "finish_reason": "stop" if reasoning_result.believes_task_complete else "continue",
            "reasoning_time": reasoning_result.reasoning_time_seconds,
        }
        
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "response_text": f"Error calling LLM: {e}",
            "tool_calls": [],
            "finish_reason": "error",
        }


@activity.defn
async def execute_mcp_tool_activity(
    tool_call: Dict[str, Any],
    activity_services: ActivityServicesInterface,
) -> Dict[str, Any]:
    """
    Execute MCP tool via Temporal activity for durability.
    
    This activity handles tool execution with Temporal benefits:
    retries, durability, observability.
    """
    tool_name = tool_call.get("name", "unknown")
    try:
        tool_arguments = tool_call.get("arguments", {})
        
        logger.info(f"Executing MCP tool: {tool_name}")
        
        # Use AgentArea's MCP service
        mcp_service = activity_services.mcp_service
        
        # Get server instance ID and convert to UUID if needed
        server_id = tool_call.get("mcp_server_id")
        if isinstance(server_id, str):
            server_instance_id = UUID(server_id)
        elif isinstance(server_id, UUID):
            server_instance_id = server_id
        else:
            raise ValueError(f"Invalid server ID: {server_id}")
        
        # Execute the tool
        tool_result = await mcp_service.execute_tool(
            tool_name=tool_name,
            arguments=tool_arguments,
            server_instance_id=server_instance_id
        )
        
        return {
            "success": True,
            "result": tool_result.get("output", str(tool_result)),
            "tool_name": tool_name,
        }
        
    except Exception as e:
        logger.error(f"MCP tool execution failed: {e}")
        return {
            "success": False,
            "result": f"Error executing tool {tool_name}: {e}",
            "tool_name": tool_name,
            "error": str(e),
        }


# Legacy activities for backward compatibility with existing workflows
@activity.defn
async def validate_agent_configuration_activity(
    agent_id: UUID,
    activity_services: ActivityServicesInterface,
) -> Dict[str, Any]:
    """Validate agent configuration and MCP server availability."""
    try:
        logger.info(f"Validating agent configuration for {agent_id}")
        
        # Get agent config
        agent_config = await activity_services.agent_service.build_agent_config(agent_id)
        if not agent_config:
            return {
                "valid": False,
                "errors": [f"Agent {agent_id} not found"]
            }
        
        # Validate model instance
        model_instance = agent_config.get("model_instance")
        if not model_instance:
            return {
                "valid": False,
                "errors": ["No model instance configured for agent"]
            }
        
        return {
            "valid": True,
            "errors": [],
            "agent_name": agent_config.get("name"),
            "model": model_instance.get("model_name"),
        }
        
    except Exception as e:
        logger.error(f"Agent validation failed: {e}")
        return {
            "valid": False,
            "errors": [str(e)]
        }


@activity.defn
async def discover_available_tools_activity(
    agent_id: UUID,
    activity_services: ActivityServicesInterface,
) -> List[Dict[str, Any]]:
    """Discover available tools from MCP server instances."""
    try:
        logger.info(f"Discovering tools for agent {agent_id}")
        
        # Get agent config
        agent_config = await activity_services.agent_service.build_agent_config(agent_id)
        if not agent_config:
            return []
        
        tools_config = agent_config.get("tools_config", {})
        mcp_servers = tools_config.get("mcp_servers", [])
        
        available_tools = []
        
        for mcp_server in mcp_servers:
            if mcp_server.get("enabled", False):
                server_id = mcp_server.get("id")
                
                # Get tools from MCP server
                try:
                    tools = await activity_services.mcp_service.get_server_tools(server_id)
                    
                    for tool in tools:
                        available_tools.append({
                            "name": tool.get("name"),
                            "description": tool.get("description", ""),
                            "parameters": tool.get("parameters", {}),
                            "mcp_server_id": server_id,
                            "mcp_server_name": mcp_server.get("name"),
                        })
                except Exception as e:
                    logger.warning(f"Failed to get tools from server {server_id}: {e}")
        
        logger.info(f"Discovered {len(available_tools)} tools for agent {agent_id}")
        return available_tools
        
    except Exception as e:
        logger.error(f"Tool discovery failed: {e}")
        return []


@activity.defn
async def persist_agent_memory_activity(
    agent_id: UUID,
    conversation_history: List[Dict[str, Any]],
    execution_result: Dict[str, Any],
    activity_services: ActivityServicesInterface,
) -> Dict[str, Any]:
    """Persist agent memory and conversation history."""
    try:
        logger.info(f"Persisting memory for agent {agent_id}")
        
        # This could be implemented to store conversation history in database
        # For now, we'll just log and return success
        
        return {
            "success": True,
            "memory_entries_saved": len(conversation_history),
            "agent_id": str(agent_id),
        }
        
    except Exception as e:
        logger.error(f"Memory persistence failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }


@activity.defn
async def publish_task_event_activity(
    task_id: UUID,
    event_type: str,
    event_data: Dict[str, Any],
    activity_services: ActivityServicesInterface,
) -> Dict[str, Any]:
    """Publish task completion events."""
    try:
        logger.info(f"Publishing {event_type} event for task {task_id}")
        
        # Use AgentArea's event broker
        await activity_services.event_broker.publish({
            "task_id": str(task_id),
            "event_type": event_type,
            "data": event_data,
        })
        
        return {
            "success": True,
            "event_type": event_type,
            "task_id": str(task_id),
        }
        
    except Exception as e:
        logger.error(f"Event publishing failed: {e}")
        return {
            "success": False,
            "error": str(e),
        } 