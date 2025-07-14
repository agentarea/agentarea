"""
Simple state machine agent workflow that orchestrates focused activities.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List, TypedDict

from temporalio import workflow
from temporalio.common import RetryPolicy

from ..models import AgentExecutionRequest, AgentExecutionResult

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State schema for agent execution."""
    messages: List[Dict[str, Any]]
    agent_id: str
    task_query: str
    max_iterations: int
    current_iteration: int
    available_tools: List[Dict[str, Any]]
    agent_config: Dict[str, Any]
    task_completed: bool
    tool_calls_made: int
    request: AgentExecutionRequest


@workflow.defn
class AgentExecutionWorkflow:
    """
    Simple state machine agent workflow that orchestrates focused activities.
    """

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Execute agent workflow using simple state machine orchestration."""
        try:
            # Build agent config
            agent_config = await workflow.execute_activity(
                "build_agent_config_activity",
                args=[request.agent_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Discover available tools
            available_tools = await workflow.execute_activity(
                "discover_available_tools_activity",
                args=[request.agent_id],
                start_to_close_timeout=timedelta(minutes=2),
            )

            # Initialize state
            state: AgentState = {
                "messages": [{"role": "user", "content": request.task_query}],
                "agent_id": str(request.agent_id),
                "task_query": request.task_query,
                "max_iterations": request.max_reasoning_iterations or 10,
                "current_iteration": 0,
                "available_tools": available_tools,
                "agent_config": agent_config,
                "task_completed": False,
                "tool_calls_made": 0,
                "request": request,
            }

            # Execute simple state machine
            final_state = await self._execute_state_machine(state)

            # Extract final response
            final_response = "Task completed"
            for message in reversed(final_state["messages"]):
                if message.get("role") == "assistant":
                    final_response = message.get("content", "Task completed")
                    break

            return AgentExecutionResult(
                task_id=request.task_id,
                agent_id=request.agent_id,
                success=True,
                final_response=final_response,
                conversation_history=final_state["messages"],
                total_tool_calls=final_state["tool_calls_made"],
                reasoning_iterations_used=final_state["current_iteration"],
                error_message=None,
            )

        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            return AgentExecutionResult(
                task_id=request.task_id,
                agent_id=request.agent_id,
                success=False,
                final_response="",
                conversation_history=[],
                total_tool_calls=0,
                reasoning_iterations_used=0,
                error_message=str(e),
            )

    async def _execute_state_machine(self, state: AgentState) -> AgentState:
        """Execute the state machine for agent reasoning."""
        while not state["task_completed"]:
            # LLM call step
            state = await self._llm_step(state)
            
            # Check if LLM wants to use tools
            if self._has_tool_calls(state):
                state = await self._tool_execution_step(state)
            
            # Check completion step
            state = await self._completion_check_step(state)
            
            # Safety check for infinite loops
            if state["current_iteration"] >= state["max_iterations"]:
                state["task_completed"] = True
                break
        
        return state

    async def _llm_step(self, state: AgentState) -> AgentState:
        """Execute LLM reasoning step."""
        llm_response = await workflow.execute_activity(
            "call_llm_activity",
            args=[
                state["messages"],
                state["agent_config"].get("model", "gpt-4"),
                state["available_tools"]
            ],
            start_to_close_timeout=timedelta(minutes=5),
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

    async def _tool_execution_step(self, state: AgentState) -> AgentState:
        """Execute tool calls if present."""
        last_message = state["messages"][-1]
        tool_calls = last_message.get("tool_calls", [])
        
        tool_messages = []
        for tool_call in tool_calls:
            logger.info(f"Executing tool: {tool_call.get('name')}")
            
            tool_result = await workflow.execute_activity(
                "execute_mcp_tool_activity",
                args=[
                    tool_call.get("name", ""),
                    tool_call.get("args", {}),
                    None  # server_instance_id
                ],
                start_to_close_timeout=timedelta(minutes=2),
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

    async def _completion_check_step(self, state: AgentState) -> AgentState:
        """Check if task should be completed."""
        check_result = await workflow.execute_activity(
            "check_task_completion_activity",
            args=[
                state["messages"],
                state["current_iteration"],
                state["max_iterations"]
            ],
            start_to_close_timeout=timedelta(minutes=1),
        )
        
        task_completed = check_result.get("should_complete", False)
        
        return {
            **state,
            "task_completed": task_completed,
        }

    def _has_tool_calls(self, state: AgentState) -> bool:
        """Check if the last message has tool calls."""
        if not state["messages"]:
            return False
        
        last_message = state["messages"][-1]
        tool_calls = last_message.get("tool_calls", [])
        return len(tool_calls) > 0

    @workflow.query
    def get_execution_status(self) -> Dict[str, Any]:
        return {
            "status": "Simple state machine execution via orchestrated activities",
            "workflow_type": "StateMachine",
        } 