"""Temporal-based agent execution runner for workflow orchestration."""

import logging
from dataclasses import dataclass, field
from typing import Any

from agentarea_agents_sdk.runners import (
    AgentGoal,
    BaseAgentRunner,
    ExecutionResult,
    Message,
    RunnerConfig,
)
from temporalio import workflow

logger = logging.getLogger(__name__)


@dataclass
class TemporalExecutionState:
    """Execution state for Temporal runner."""

    goal: AgentGoal
    messages: list[Message] = field(default_factory=list)
    current_iteration: int = 0
    success: bool = False
    final_response: str | None = None
    total_cost: float = 0.0
    # Additional Temporal-specific fields
    agent_config: dict[str, Any] = field(default_factory=dict)
    available_tools: list[dict[str, Any]] = field(default_factory=list)


class TemporalAgentRunner(BaseAgentRunner):
    """Temporal-based agent execution runner for workflow orchestration.

    This runner integrates with Temporal workflows and uses activities
    for infrastructure concerns while maintaining the same interface
    as other runners.
    """

    def __init__(
        self,
        activities_interface,
        event_manager=None,
        budget_tracker=None,
        config: RunnerConfig | None = None,
    ):
        """Initialize the Temporal runner.

        Args:
            activities_interface: Temporal activities interface
            event_manager: Event manager for tracking (optional)
            budget_tracker: Budget tracker (optional)
            config: Runner configuration (optional)
        """
        super().__init__(config)
        self.activities = activities_interface
        self.event_manager = event_manager
        self.budget_tracker = budget_tracker
        self.terminator.budget_tracker = budget_tracker

        # Temporal-specific state
        self._paused = False
        self._pause_reason = ""

    async def run(self, goal: AgentGoal, workflow_state=None) -> ExecutionResult:
        """Execute the agent workflow using Temporal activities.

        Args:
            goal: The goal to achieve
            workflow_state: Optional existing workflow state

        Returns:
            ExecutionResult with final results
        """
        # Create or use existing state
        if workflow_state:
            state = workflow_state
            state.goal = goal
        else:
            state = TemporalExecutionState(goal=goal)

        # Add system message if first run
        if not state.messages:
            system_prompt = self._build_system_prompt(goal)
            state.messages.append(Message(role="system", content=system_prompt))

        workflow.logger.info(f"Starting Temporal agent execution for goal: {goal.description}")

        # Use the unified main loop with pause support
        result = await self._execute_main_loop(
            state, pause_check=lambda: self._paused, wait_for_unpause=self._wait_for_unpause
        )

        return result

    async def _execute_iteration(self, state: TemporalExecutionState) -> None:
        """Execute a single iteration using Temporal activities."""
        iteration = state.current_iteration

        # Log iteration start
        if self.event_manager:
            self.event_manager.add_event(
                "iteration_started",
                {
                    "iteration": iteration,
                    "budget_remaining": self.budget_tracker.get_remaining()
                    if self.budget_tracker
                    else 0,
                },
            )

        try:
            # Execute the iteration using activities
            await self._execute_temporal_iteration(state)

            # Check budget warnings
            await self._check_budget_status()

            # Log iteration completion
            if self.event_manager:
                self.event_manager.add_event(
                    "iteration_completed", {"iteration": iteration, "success": True}
                )

        except Exception as e:
            # Log iteration failure
            if self.event_manager:
                self.event_manager.add_event(
                    "iteration_failed", {"iteration": iteration, "error": str(e)}
                )
            raise

    async def _execute_temporal_iteration(self, state: TemporalExecutionState) -> None:
        """Execute iteration using Temporal activities."""
        from temporalio.common import RetryPolicy

        from ..models import LLMCallRequest
        from ..workflows.constants import (
            DEFAULT_RETRY_ATTEMPTS,
            LLM_CALL_TIMEOUT,
            Activities,
        )

        # Convert messages to dict format for request
        messages_dict = [
            {
                "role": msg.role,
                "content": msg.content,
                "tool_call_id": msg.tool_call_id,
                "name": msg.name,
            }
            for msg in state.messages
        ]

        # Create Pydantic request model for LLM call
        # Extract workspace_id and user_id from agent_config.user_context_data
        user_context_data = state.agent_config.get("user_context_data", {})
        workspace_id = user_context_data.get("workspace_id")
        user_id = user_context_data.get("user_id")

        if not workspace_id:
            raise ValueError(
                "Missing workspace_id in agent_config.user_context_data for workflow execution"
            )
        if not user_id:
            raise ValueError(
                "Missing user_id in agent_config.user_context_data for workflow execution"
            )

        llm_request = LLMCallRequest(
            messages=messages_dict,
            model_id=state.agent_config.get("model_id") or "gpt-4",  # Provide default model
            tools=state.available_tools,
            workspace_id=workspace_id,
            user_context_data=user_context_data,
        )

        # Call LLM via activity using Pydantic model
        response = await workflow.execute_activity(
            Activities.CALL_LLM,
            args=[llm_request],
            start_to_close_timeout=LLM_CALL_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        # Extract usage info and update budget
        if self.budget_tracker:
            usage_info = self._extract_usage_info(response)
            self.budget_tracker.add_cost(usage_info["cost"])

        # Convert response to Message
        message_data = response.get("message", {})
        assistant_message = Message(
            role=message_data.get("role", "assistant"),
            content=message_data.get("content", ""),
            tool_call_id=message_data.get("tool_call_id"),
            name=message_data.get("name"),
        )

        # Add assistant message
        state.messages.append(assistant_message)

        # Handle tool calls
        tool_calls = self._extract_tool_calls(assistant_message)
        if tool_calls:
            await self._handle_temporal_tool_calls(state, tool_calls)

        # Evaluate goal progress
        await self._evaluate_temporal_goal_progress(state)

    async def _handle_temporal_tool_calls(
        self, state: TemporalExecutionState, tool_calls: list[dict[str, Any]]
    ) -> None:
        """Handle tool calls using Temporal activities."""
        from temporalio.common import RetryPolicy

        from ..models import MCPToolRequest
        from ..workflows.constants import DEFAULT_RETRY_ATTEMPTS, TOOL_EXECUTION_TIMEOUT, Activities

        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]

            try:
                # Parse tool arguments
                import json

                try:
                    tool_args = json.loads(tool_call["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    tool_args = {}

                # Extract workspace_id from agent_config.user_context_data
                user_context_data = state.agent_config.get("user_context_data", {})
                workspace_id = user_context_data.get("workspace_id")

                if not workspace_id:
                    raise ValueError(
                        "Missing workspace_id in agent_config.user_context_data for MCP tool execution"
                    )

                # Create Pydantic request model for MCP tool execution
                mcp_request = MCPToolRequest(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    server_instance_id=None,
                    workspace_id=workspace_id,
                    tools_config=state.agent_config.get("tools_config"),
                )

                # Execute tool call via activity using Pydantic model
                result = await workflow.execute_activity(
                    Activities.EXECUTE_MCP_TOOL,
                    args=[mcp_request],
                    start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
                )

                # Add tool result to messages
                state.messages.append(
                    Message(
                        role="tool",
                        tool_call_id=tool_call["id"],
                        name=tool_name,
                        content=str(
                            result.result if hasattr(result, "result") else result.get("result", "")
                        ),
                    )
                )

                # Check if completion tool was called
                if tool_name == "task_complete" and (
                    hasattr(result, "result") and "completed" in str(result.result)
                ):
                    state.success = True
                    state.final_response = str(
                        result.result
                        if hasattr(result, "result")
                        else result.get("result", "Task completed")
                    )

            except Exception as e:
                workflow.logger.error(f"Tool call {tool_name} failed: {e}")

                # Add error message
                state.messages.append(
                    Message(
                        role="tool",
                        tool_call_id=tool_call["id"],
                        name=tool_name,
                        content=f"Tool execution failed: {e}",
                    )
                )

    async def _evaluate_temporal_goal_progress(self, state: TemporalExecutionState) -> None:
        """Evaluate goal progress using Temporal activities."""
        from temporalio.common import RetryPolicy

        from ..models import GoalEvaluationRequest
        from ..workflows.constants import ACTIVITY_TIMEOUT, DEFAULT_RETRY_ATTEMPTS, Activities

        try:
            # Convert goal to dict for request
            goal_dict = {
                "id": str(state.goal.context.get("id", "unknown")),
                "description": state.goal.description,
                "success_criteria": state.goal.success_criteria,
                "max_iterations": state.goal.max_iterations,
                "requires_human_approval": False,
                "context": state.goal.context,
            }

            # Convert messages to dict format for request
            messages_dict = [{"role": msg.role, "content": msg.content} for msg in state.messages]

            # Create Pydantic request model for goal evaluation
            evaluation_request = GoalEvaluationRequest(
                goal=goal_dict, messages=messages_dict, current_iteration=state.current_iteration
            )

            evaluation = await workflow.execute_activity(
                Activities.EVALUATE_GOAL_PROGRESS,
                args=[evaluation_request],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Handle Pydantic result model
            if hasattr(evaluation, "goal_achieved") and evaluation.goal_achieved:
                state.success = True
                state.final_response = evaluation.final_response
            elif isinstance(evaluation, dict) and evaluation.get("goal_achieved", False):
                state.success = True
                state.final_response = evaluation.get("final_response")

        except Exception as e:
            workflow.logger.warning(f"Goal evaluation failed: {e}")

    async def _check_budget_status(self) -> None:
        """Check budget status and send warnings if needed."""
        if not self.budget_tracker:
            return

        if self.budget_tracker.should_warn():
            if self.event_manager:
                self.event_manager.add_event(
                    "budget_warning",
                    {
                        "usage_percentage": self.budget_tracker.get_usage_percentage(),
                        "cost": self.budget_tracker.cost,
                        "limit": self.budget_tracker.budget_limit,
                        "message": self.budget_tracker.get_warning_message(),
                    },
                )
            self.budget_tracker.mark_warning_sent()

        if self.budget_tracker.is_exceeded():
            if self.event_manager:
                self.event_manager.add_event(
                    "budget_exceeded",
                    {
                        "cost": self.budget_tracker.cost,
                        "limit": self.budget_tracker.budget_limit,
                        "message": self.budget_tracker.get_exceeded_message(),
                    },
                )

    def _build_system_prompt(self, goal: AgentGoal) -> str:
        """Build system prompt for the agent."""
        return f"""You are an AI assistant helping to achieve the following goal:

GOAL: {goal.description}

SUCCESS CRITERIA:
{chr(10).join(f"- {criterion}" for criterion in goal.success_criteria)}

You have a maximum of {goal.max_iterations} iterations to complete this task.

Work step by step towards achieving the goal. Use available tools as needed."""

    def _extract_usage_info(self, response: dict[str, Any]) -> dict[str, Any]:
        """Extract usage information from LLM response."""
        # This would extract cost and usage info from the response
        # Implementation depends on the response format
        return {"cost": 0.0, "usage": {}}

    def _extract_tool_calls(self, message: Message) -> list[dict[str, Any]]:
        """Extract tool calls from assistant message."""
        # This would parse tool calls from the message
        # Implementation depends on the message format
        return []

    # Temporal-specific pause/resume functionality
    async def _wait_for_unpause(self) -> None:
        """Wait for unpause signal."""
        await workflow.wait_condition(lambda: not self._paused)

    def pause(self, reason: str = "Manual pause") -> None:
        """Pause workflow execution."""
        self._paused = True
        self._pause_reason = reason
        workflow.logger.info(f"Workflow paused: {reason}")

    def resume(self, reason: str = "Manual resume") -> None:
        """Resume workflow execution."""
        self._paused = False
        self._pause_reason = ""
        workflow.logger.info(f"Workflow resumed: {reason}")
