"""
LangGraph-based agent workflow that calls a LangGraph activity.
"""

import logging
from datetime import timedelta
from typing import Any, Dict
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy

from ..models import AgentExecutionRequest, AgentExecutionResult
from ..activities.agent_execution_activities import (
    build_agent_config_activity,
    discover_available_tools_activity,
    call_llm_activity,
    execute_mcp_tool_activity,
    check_task_completion_activity,
)

logger = logging.getLogger(__name__)


@workflow.defn
class AgentExecutionWorkflow:
    """
    LangGraph-based agent workflow that orchestrates activities step-by-step.
    """

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Execute agent workflow by orchestrating LangGraph activities."""
        try:
            agent_id = request.agent_id
            task_query = request.task_query
            max_iterations = request.max_reasoning_iterations or 10
            
            # Build agent config
            agent_config = await workflow.execute_activity(
                build_agent_config_activity,
                args=[agent_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # 2. Discover available tools
            available_tools = await workflow.execute_activity(
                discover_available_tools_activity,
                args=[agent_id],
                start_to_close_timeout=timedelta(minutes=2),
            )

            # 3. Initialize state
            messages = [{"role": "user", "content": task_query}]
            current_iteration = 0
            tool_calls_made = 0
            task_completed = False
            error_message = None

            # 4. Main loop (LangGraph logic)
            while not task_completed and current_iteration < max_iterations:
                # LLM call
                llm_response = await workflow.execute_activity(
                    call_llm_activity,
                    args=[messages, agent_config.get("model", "gpt-4"), available_tools],
                    start_to_close_timeout=timedelta(minutes=5),
                )
                if not isinstance(llm_response, dict):
                    raise RuntimeError("LLM activity did not return a dict")
                assistant_message = {
                    "role": "assistant",
                    "content": llm_response.get("content", ""),
                    "tool_calls": llm_response.get("tool_calls", []),
                }
                messages.append(assistant_message)
                current_iteration += 1

                # If there are tool calls, execute them
                tool_calls = assistant_message.get("tool_calls", [])
                if tool_calls:
                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name", "")
                        tool_args = tool_call.get("args", {})
                        tool_result = await workflow.execute_activity(
                            execute_mcp_tool_activity,
                            args=[tool_name, tool_args, None],
                            start_to_close_timeout=timedelta(minutes=2),
                        )
                        tool_message = {
                            "role": "tool",
                            "content": str(tool_result),
                            "tool_call_id": tool_call.get("id", ""),
                            "tool_name": tool_name,
                        }
                        messages.append(tool_message)
                        tool_calls_made += 1

                # Check for completion
                check_result = await workflow.execute_activity(
                    check_task_completion_activity,
                    args=[messages, current_iteration, max_iterations],
                    start_to_close_timeout=timedelta(minutes=1),
                )
                if not isinstance(check_result, dict):
                    raise RuntimeError("Check completion activity did not return a dict")
                task_completed = check_result.get("should_complete", False)

            # Extract final response
            final_response = "Task completed"
            for message in reversed(messages):
                if message.get("role") == "assistant":
                    final_response = message.get("content", "Task completed")
                    break

            return AgentExecutionResult(
                task_id=request.task_id,
                agent_id=agent_id,
                success=True,
                final_response=final_response,
                conversation_history=messages,
                total_tool_calls=tool_calls_made,
                reasoning_iterations_used=current_iteration,
                error_message=error_message,
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

    @workflow.query
    def get_execution_status(self) -> Dict[str, Any]:
        return {
            "status": "LangGraph execution via orchestrated activities",
            "workflow_type": "LangGraph",
        } 