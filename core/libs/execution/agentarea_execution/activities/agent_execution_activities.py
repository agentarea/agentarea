"""
LangGraph-based agent execution activities for Temporal workflows.

This module provides Temporal activities for LangGraph-based agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: LiteLLM for flexible model provider support
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from temporalio import activity

from ..interfaces import ActivityServicesInterface

logger = logging.getLogger(__name__)

# Global services for standalone activity functions
_global_services: Optional[ActivityServicesInterface] = None

def set_global_services(services: ActivityServicesInterface) -> None:
    """Set global services for standalone activity functions."""
    global _global_services
    _global_services = services

def get_global_services() -> ActivityServicesInterface:
    """Get global services, raising error if not set."""
    if _global_services is None:
        raise RuntimeError("Global services not set. Call set_global_services() first.")
    return _global_services


class AgentActivities:
    """
    Simplified agent activities for LangGraph workflows.
    
    Each activity handles a specific piece of logic that workflow nodes can call.
    The LangGraph itself is defined in the workflow, not here.
    """
    
    def __init__(self, services: ActivityServicesInterface):
        self.services = services
        from ..llm_model_resolver import LLMModelResolver
        self.llm_model_resolver = LLMModelResolver()

    @activity.defn
    async def build_agent_config_activity(
        self,
        agent_id: UUID,
        execution_context: Optional[Dict[str, Any]] = None,
        step_type: Optional[str] = None,
        override_model: Optional[str] = None,
    ) -> Dict[str, Any]:
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
    ) -> List[Dict[str, Any]]:
        """Discover available tools for an agent."""
        try:
            agent_config = await self.services.agent_service.build_agent_config(agent_id)
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found")
            mcp_server_ids = agent_config.get("mcp_server_ids", [])
            all_tools: List[Dict[str, Any]] = []
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
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
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
                "content": f"Error: {str(e)}",
                "tool_calls": [],
                "finish_reason": "error"
            }

    @activity.defn
    async def execute_mcp_tool_activity(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        server_instance_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
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
        messages: List[Dict[str, Any]],
        current_iteration: int,
        max_iterations: int,
    ) -> Dict[str, Any]:
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

    @activity.defn
    async def execute_langgraph_activity(
        self,
        agent_id: UUID,
        task_query: str,
        max_iterations: int = 10,
    ) -> Dict[str, Any]:
        """
        Execute the complete LangGraph-based agent workflow.
        
        This activity contains all the LangGraph logic since Temporal workflows 
        cannot import LangGraph due to network dependency restrictions.
        """
        try:
            # Import LangGraph here in the activity (not in workflow)
            from langgraph.graph import StateGraph, START, END
            from typing import TypedDict
            
            # Define state schema inside the activity
            class AgentState(TypedDict):
                messages: List[Dict[str, Any]]
                agent_id: str
                task_query: str
                max_iterations: int
                current_iteration: int
                available_tools: List[Dict[str, Any]]
                agent_config: Dict[str, Any]
                task_completed: bool
                tool_calls_made: int
            
            # Get agent configuration
            agent_config = await self.build_agent_config_activity(agent_id)
            if not agent_config:
                raise ValueError(f"Agent {agent_id} not found")
            
            # Discover available tools
            available_tools = await self.discover_available_tools_activity(agent_id)
            
            # Create initial state
            initial_state: AgentState = {
                "messages": [{"role": "user", "content": task_query}],
                "agent_id": str(agent_id),
                "task_query": task_query,
                "max_iterations": max_iterations,
                "current_iteration": 0,
                "available_tools": available_tools,
                "agent_config": agent_config,
                "task_completed": False,
                "tool_calls_made": 0,
            }
            
            # Build and execute the graph
            graph = self._build_activity_graph()
            final_state = await graph.ainvoke(initial_state)
            
            # Extract final response
            final_response = self._get_final_response(final_state["messages"])
            
            return {
                "success": True,
                "final_response": final_response,
                "conversation_history": final_state["messages"],
                "total_tool_calls": final_state["tool_calls_made"],
                "reasoning_iterations_used": final_state["current_iteration"],
                "error_message": None,
            }
            
        except Exception as e:
            logger.error(f"LangGraph execution failed for {agent_id}: {e}")
            return {
                "success": False,
                "final_response": "",
                "conversation_history": [],
                "total_tool_calls": 0,
                "reasoning_iterations_used": 0,
                "error_message": str(e),
            }
    
    def _build_activity_graph(self):
        """Build the LangGraph inside the activity."""
        from langgraph.graph import StateGraph, START, END
        
        # Define state schema
        from typing import TypedDict
        class AgentState(TypedDict):
            messages: List[Dict[str, Any]]
            agent_id: str
            task_query: str
            max_iterations: int
            current_iteration: int
            available_tools: List[Dict[str, Any]]
            agent_config: Dict[str, Any]
            task_completed: bool
            tool_calls_made: int
        
        graph = StateGraph(AgentState)
        
        # Add nodes
        graph.add_node("llm_call", self._activity_llm_node)
        graph.add_node("tool_execution", self._activity_tool_node)
        graph.add_node("check_completion", self._activity_check_node)
        
        # Define the flow
        graph.add_edge(START, "llm_call")
        graph.add_conditional_edges(
            "llm_call",
            self._activity_route_after_llm,
            {
                "tools": "tool_execution",
                "check": "check_completion"
            }
        )
        graph.add_edge("tool_execution", "check_completion")
        graph.add_conditional_edges(
            "check_completion",
            self._activity_route_after_check,
            {
                "continue": "llm_call",
                "end": END
            }
        )
        
        return graph.compile()
    
    async def _activity_llm_node(self, state):
        """LLM node that calls the LLM activity."""
        llm_response = await self.call_llm_activity(
            state["messages"],
            state["agent_config"].get("model", "gpt-4"),
            state["available_tools"]
        )
        
        # Add LLM response to conversation
        assistant_message = {
            "role": "assistant",
            "content": llm_response.get("content", ""),
            "tool_calls": llm_response.get("tool_calls", [])
        }
        
        return {
            **state,
            "messages": state["messages"] + [assistant_message],
            "current_iteration": state["current_iteration"] + 1,
        }
    
    async def _activity_tool_node(self, state):
        """Tool execution node that calls tool activities."""
        last_message = state["messages"][-1]
        tool_calls = last_message.get("tool_calls", [])
        
        tool_messages = []
        for tool_call in tool_calls:
            logger.info(f"Executing tool: {tool_call.get('name')}")
            
            tool_result = await self.execute_mcp_tool_activity(
                tool_call.get("name", ""),
                tool_call.get("args", {}),
                None  # server_instance_id
            )
            
            tool_message = {
                "role": "tool",
                "content": str(tool_result),
                "tool_call_id": tool_call.get("id", ""),
                "tool_name": tool_call.get("name", "")
            }
            tool_messages.append(tool_message)
        
        return {
            **state,
            "messages": state["messages"] + tool_messages,
            "tool_calls_made": state["tool_calls_made"] + len(tool_messages),
        }
    
    async def _activity_check_node(self, state):
        """Check completion node."""
        task_completed = (
            state["current_iteration"] >= state["max_iterations"] or
            self._last_message_indicates_completion(state["messages"])
        )
        
        return {
            **state,
            "task_completed": task_completed,
        }
    
    def _activity_route_after_llm(self, state) -> str:
        """Route after LLM call."""
        last_message = state["messages"][-1]
        tool_calls = last_message.get("tool_calls", [])
        
        if tool_calls:
            return "tools"
        else:
            return "check"
    
    def _activity_route_after_check(self, state) -> str:
        """Route after completion check."""
        if state["task_completed"]:
            return "end"
        else:
            return "continue"
    
    def _last_message_indicates_completion(self, messages: List[Dict[str, Any]]) -> bool:
        """Check if the last assistant message indicates completion."""
        for message in reversed(messages):
            if message.get("role") == "assistant":
                content = message.get("content", "").lower()
                completion_indicators = [
                    "task complete",
                    "finished",
                    "done",
                    "completed successfully"
                ]
                return any(indicator in content for indicator in completion_indicators)
        return False
    
    def _get_final_response(self, messages: List[Dict[str, Any]]) -> str:
        """Extract final response from conversation."""
        for message in reversed(messages):
            if message.get("role") == "assistant":
                return message.get("content", "Task completed")
        return "Task completed"


# =================================================================
# GLOBAL ACTIVITIES MANAGEMENT
# =================================================================

# _global_activities: Optional[AgentActivities] = None # Removed global instance


# def set_global_activities(activities: AgentActivities) -> None: # Removed global setter
#     global _global_activities
#     _global_activities = activities


# def get_global_activities() -> AgentActivities: # Removed global getter
#     if _global_activities is None:
#         raise RuntimeError("Global activities not set. Call set_global_activities() first.")
#     return _global_activities


# =================================================================
# TEMPORAL ACTIVITY EXPORTS
# =================================================================

@activity.defn
async def build_agent_config_activity(
    agent_id: UUID,
    execution_context: Optional[Dict[str, Any]] = None,
    step_type: Optional[str] = None,
    override_model: Optional[str] = None,
) -> Dict[str, Any]:
    activities = AgentActivities(get_global_services())
    return await activities.build_agent_config_activity(
        agent_id, execution_context, step_type, override_model
    )


@activity.defn
async def discover_available_tools_activity(agent_id: UUID) -> List[Dict[str, Any]]:
    activities = AgentActivities(get_global_services())
    return await activities.discover_available_tools_activity(agent_id)


@activity.defn
async def call_llm_activity(
    messages: List[Dict[str, Any]],
    model: str,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    activities = AgentActivities(get_global_services())
    return await activities.call_llm_activity(messages, model, tools)


@activity.defn
async def execute_mcp_tool_activity(
    tool_name: str,
    tool_args: Dict[str, Any],
    server_instance_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    activities = AgentActivities(get_global_services())
    return await activities.execute_mcp_tool_activity(tool_name, tool_args, server_instance_id)


@activity.defn
async def check_task_completion_activity(
    messages: List[Dict[str, Any]],
    current_iteration: int,
    max_iterations: int,
) -> Dict[str, Any]:
    activities = AgentActivities(get_global_services())
    return await activities.check_task_completion_activity(messages, current_iteration, max_iterations)