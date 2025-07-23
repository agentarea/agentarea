"""Refactored agent execution workflow - clean, maintainable, and DRY.

This is a simplified version of the original 1066-line workflow file,
broken down into focused methods with helper classes for better maintainability.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID
    from .helpers import BudgetTracker, EventManager, MessageBuilder, StateValidator, ToolCallExtractor

from ..models import AgentExecutionRequest, AgentExecutionResult
from .constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    EVENT_PUBLISH_RETRY_ATTEMPTS,
    EVENT_PUBLISH_TIMEOUT,
    LLM_CALL_TIMEOUT,
    MAX_ITERATIONS,
    TOOL_EXECUTION_TIMEOUT,
    Activities,
    EventTypes,
    ExecutionStatus,
)


@dataclass
class AgentGoal:
    """Agent goal definition."""
    id: str
    description: str
    success_criteria: list[str]
    max_iterations: int
    requires_human_approval: bool
    context: dict[str, Any]


@dataclass
class AgentExecutionState:
    """Simplified execution state with direct attribute access."""
    execution_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    goal: AgentGoal | None = None
    status: str = ExecutionStatus.INITIALIZING
    current_iteration: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    agent_config: dict[str, Any] = field(default_factory=dict)
    available_tools: list[dict[str, Any]] = field(default_factory=list)
    final_response: str | None = None
    success: bool = False
    budget_usd: float | None = None


@workflow.defn
class AgentExecutionWorkflow:
    """Simplified and maintainable agent execution workflow."""

    def __init__(self):
        self.state = AgentExecutionState()
        self.event_manager: EventManager | None = None
        self.budget_tracker: BudgetTracker | None = None
        self._paused = False
        self._pause_reason = ""

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Main workflow execution method."""
        try:
            # Initialize workflow
            await self._initialize_workflow(request)

            # Main execution loop
            result = await self._execute_main_loop()

            # Finalize and return result
            return await self._finalize_execution(result)

        except Exception as e:
            workflow.logger.error(f"Workflow execution failed: {e}")
            await self._handle_workflow_error(e)
            raise

    async def _initialize_workflow(self, request: AgentExecutionRequest) -> None:
        """Initialize workflow state and dependencies."""
        workflow.logger.info(f"Initializing workflow for agent {request.agent_id}")

        # Populate state attributes
        self.state.execution_id = workflow.info().workflow_id
        self.state.agent_id = str(request.agent_id)
        self.state.task_id = str(request.task_id)
        self.state.goal = self._build_goal_from_request(request)
        self.state.status = ExecutionStatus.INITIALIZING
        self.state.budget_usd = request.budget_usd

        # Initialize helpers
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id
        )
        self.budget_tracker = BudgetTracker(self.state.budget_usd)

        # Add workflow started event
        self.event_manager.add_event(EventTypes.WORKFLOW_STARTED, {
            "goal_description": self.state.goal.description,
            "max_iterations": self.state.goal.max_iterations,
            "budget_limit": self.budget_tracker.budget_limit
        })

        # Publish immediately
        await self._publish_events_immediately()

        # Initialize agent configuration
        await self._initialize_agent_config()

    async def _initialize_agent_config(self) -> None:
        """Initialize agent configuration and available tools."""
        workflow.logger.info("Initializing agent configuration")

        # Build agent config
        self.state.agent_config = await workflow.execute_activity(
            Activities.BUILD_AGENT_CONFIG,
            UUID(self.state.agent_id),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
        )

        # Validate configuration
        if not StateValidator.validate_agent_config(self.state.agent_config):
            raise ApplicationError("Invalid agent configuration")

        # Discover available tools
        self.state.available_tools = await workflow.execute_activity(
            Activities.DISCOVER_AVAILABLE_TOOLS,
            UUID(self.state.agent_id),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
        )

        if not StateValidator.validate_tools(self.state.available_tools):
            raise ApplicationError("Invalid tools configuration")

    async def _execute_main_loop(self) -> dict[str, Any]:
        """Main execution loop with dynamic termination conditions."""
        workflow.logger.info("Starting main execution loop")

        self.state.status = ExecutionStatus.EXECUTING

        while True:
            # Increment iteration count
            self.state.current_iteration += 1

            # Check if we should continue before starting the iteration
            should_continue, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(f"Stopping execution before iteration {self.state.current_iteration}: {reason}")
                # Decrement since we didn't actually execute this iteration
                self.state.current_iteration -= 1
                break

            workflow.logger.info(f"Starting iteration {self.state.current_iteration}")

            # Execute iteration
            await self._execute_iteration()

            # Publish events after each iteration
            await self._publish_events()

            # Check if we should finish after completing the iteration
            should_continue, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(f"Stopping execution after iteration {self.state.current_iteration}: {reason}")
                break

            # Check for pause
            if self._paused:
                await workflow.wait_condition(lambda: not self._paused)

        return {"iterations_completed": self.state.current_iteration}

    def _should_continue_execution(self) -> tuple[bool, str]:
        """Comprehensive check for whether execution should continue.
        
        Checks all termination conditions:
        - Goal achievement 
        - Maximum iterations reached
        - Budget exceeded
        - Workflow cancelled/paused state
        
        Returns:
            tuple[bool, str]: (should_continue, reason_for_stopping)
        """
        # Check if goal is achieved (highest priority)
        if self.state.success:
            return False, "Goal achieved successfully"

        # Check maximum iterations
        max_iterations = self.state.goal.max_iterations if self.state.goal else MAX_ITERATIONS
        if self.state.current_iteration >= max_iterations:
            return False, f"Maximum iterations reached ({max_iterations})"

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            return False, f"Budget exceeded (${self.budget_tracker.cost:.2f}/${self.budget_tracker.budget_limit:.2f})"

        # Check for cancellation (this could be extended for other cancellation conditions)
        # For now, we don't have explicit cancellation, but this is where it would go

        # If we get here, execution should continue
        return True, "Continue execution"

    async def _execute_iteration(self) -> None:
        """Execute a single iteration."""
        iteration = self.state.current_iteration

        self.event_manager.add_event(EventTypes.ITERATION_STARTED, {
            "iteration": iteration,
            "budget_remaining": self.budget_tracker.get_remaining()
        })
        await self._publish_events_immediately()

        try:
            # Build system prompt with current context
            if self.state.goal:
                system_prompt = MessageBuilder.build_system_prompt(
                    goal_description=self.state.goal.description,
                    success_criteria=self.state.goal.success_criteria,
                    available_tools=self.state.available_tools,
                    current_iteration=iteration,
                    max_iterations=self.state.goal.max_iterations,
                    budget_remaining=self.budget_tracker.get_remaining()
                )

                # Add system message if first iteration
                if iteration == 1:
                    self.state.messages.append({
                        "role": "system",
                        "content": system_prompt
                    })

            # Call LLM
            llm_response = await self._call_llm()

            # Process LLM response
            await self._process_llm_response(llm_response)

            # Check budget warnings
            await self._check_budget_status()

            self.event_manager.add_event(EventTypes.ITERATION_COMPLETED, {
                "iteration": iteration,
                "total_cost": self.budget_tracker.cost
            })
            await self._publish_events_immediately()

        except Exception as e:
            workflow.logger.error(f"Iteration {iteration} failed: {e}")
            self.event_manager.add_event(EventTypes.LLM_CALL_FAILED, {
                "iteration": iteration,
                "error": str(e)
            })
            raise

    async def _call_llm(self) -> dict[str, Any]:
        """Call LLM with current messages."""
        self.event_manager.add_event(EventTypes.LLM_CALL_STARTED, {
            "iteration": self.state.current_iteration,
            "message_count": len(self.state.messages)
        })
        await self._publish_events_immediately()

        try:
            response = await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[
                    self.state.messages,
                    self.state.agent_config.get("model_id", "gpt-4"),
                    self.state.available_tools
                ],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
            )

            # Extract usage info and update budget
            usage_info = ToolCallExtractor.extract_usage_info(response)
            self.budget_tracker.add_cost(usage_info["cost"])

            self.event_manager.add_event(EventTypes.LLM_CALL_COMPLETED, {
                "iteration": self.state.current_iteration,
                "cost": usage_info["cost"],
                "total_cost": self.budget_tracker.cost,
                "usage": usage_info
            })
            await self._publish_events_immediately()

            return response

        except Exception as e:
            self.event_manager.add_event(EventTypes.LLM_CALL_FAILED, {
                "iteration": self.state.current_iteration,
                "error": str(e)
            })
            await self._publish_events_immediately()
            raise

    async def _process_llm_response(self, response: dict[str, Any]) -> None:
        """Process LLM response and handle tool calls."""
        message = response.get("message", {})
        self.state.messages.append(message)

        # Extract and execute tool calls
        tool_calls = ToolCallExtractor.extract_tool_calls(message)

        if tool_calls:
            await self._execute_tool_calls(tool_calls)

        # Check if goal is achieved
        await self._evaluate_goal_progress()

    async def _execute_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        """Execute all tool calls from LLM response."""
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]

            self.event_manager.add_event(EventTypes.TOOL_CALL_STARTED, {
                "tool_name": tool_name,
                "tool_call_id": tool_call["id"],
                "iteration": self.state.current_iteration
            })
            await self._publish_events_immediately()

            try:
                # Execute tool call
                result = await workflow.execute_activity(
                    Activities.EXECUTE_MCP_TOOL,
                    args=[
                        tool_name,
                        tool_call["function"]["arguments"]
                    ],
                    start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
                )

                # Add tool result to messages
                self.state.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": str(result.get("result", ""))
                })

                self.event_manager.add_event(EventTypes.TOOL_CALL_COMPLETED, {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call["id"],
                    "success": result.get("success", False),
                    "iteration": self.state.current_iteration
                })
                await self._publish_events_immediately()

            except Exception as e:
                workflow.logger.error(f"Tool call {tool_name} failed: {e}")

                # Add error message
                self.state.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": f"Tool execution failed: {e}"
                })

                self.event_manager.add_event(EventTypes.TOOL_CALL_FAILED, {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call["id"],
                    "error": str(e),
                    "iteration": self.state.current_iteration
                })
                await self._publish_events_immediately()

    async def _evaluate_goal_progress(self) -> None:
        """Evaluate if the goal has been achieved."""
        try:
            if self.state.goal:
                # Convert AgentGoal dataclass to dict for activity
                goal_dict = {
                    "id": self.state.goal.id,
                    "description": self.state.goal.description,
                    "success_criteria": self.state.goal.success_criteria,
                    "max_iterations": self.state.goal.max_iterations,
                    "requires_human_approval": self.state.goal.requires_human_approval,
                    "context": self.state.goal.context
                }

                evaluation = await workflow.execute_activity(
                    Activities.EVALUATE_GOAL_PROGRESS,
                    args=[
                        goal_dict,
                        self.state.messages,
                        self.state.current_iteration
                    ],
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
                )

                self.state.success = evaluation.get("goal_achieved", False)
                self.state.final_response = evaluation.get("final_response")

        except Exception as e:
            workflow.logger.warning(f"Goal evaluation failed: {e}")

    async def _check_budget_status(self) -> None:
        """Check budget status and send warnings if needed."""
        if self.budget_tracker.should_warn():
            self.event_manager.add_event(EventTypes.BUDGET_WARNING, {
                "usage_percentage": self.budget_tracker.get_usage_percentage(),
                "cost": self.budget_tracker.cost,
                "limit": self.budget_tracker.budget_limit,
                "message": self.budget_tracker.get_warning_message()
            })
            await self._publish_events_immediately()
            self.budget_tracker.mark_warning_sent()

        if self.budget_tracker.is_exceeded():
            self.event_manager.add_event(EventTypes.BUDGET_EXCEEDED, {
                "cost": self.budget_tracker.cost,
                "limit": self.budget_tracker.budget_limit,
                "message": self.budget_tracker.get_exceeded_message()
            })
            await self._publish_events_immediately()

    async def _publish_events(self) -> None:
        """Publish pending events."""
        if not self.event_manager:
            return

        events = self.event_manager.get_events()
        if not events:
            return

        try:
            events_json = [json.dumps(event) for event in events]

            await workflow.execute_activity(
                Activities.PUBLISH_WORKFLOW_EVENTS,
                events_json,
                start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=EVENT_PUBLISH_RETRY_ATTEMPTS)
            )

            self.event_manager.clear_events()

        except Exception as e:
            workflow.logger.warning(f"Failed to publish events: {e}")

    async def _publish_events_immediately(self) -> None:
        """Publish events immediately as they occur - fire and forget."""
        if not self.event_manager:
            return

        pending_events = self.event_manager.get_pending_events()
        if not pending_events:
            return

        # Fire and forget - publish async without waiting for result
        workflow.logger.debug(f"Publishing {len(pending_events)} events immediately")

        # Clear pending events immediately since we're not waiting for confirmation
        self.event_manager.clear_pending_events()

        try:
            events_json = [json.dumps(event) for event in pending_events]

            # Start the activity but don't await it (fire and forget)
            workflow.start_activity(
                Activities.PUBLISH_WORKFLOW_EVENTS,
                events_json,
                start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1)  # Single attempt only
            )
        except Exception as e:
            workflow.logger.debug(f"Failed to start event publishing (non-critical): {e}")

    async def _finalize_execution(self, result: dict[str, Any]) -> AgentExecutionResult:
        """Finalize workflow execution and return result."""
        workflow.logger.info("Finalizing workflow execution")

        # Determine final status
        if self.state.success:
            self.state.status = ExecutionStatus.COMPLETED
            event_type = EventTypes.WORKFLOW_COMPLETED
        else:
            self.state.status = ExecutionStatus.FAILED
            event_type = EventTypes.WORKFLOW_FAILED

        # Add final event
        self.event_manager.add_event(event_type, {
            "success": self.state.success,
            "iterations_completed": self.state.current_iteration,
            "total_cost": self.budget_tracker.cost,
            "final_response": self.state.final_response
        })

        # Publish final events immediately
        await self._publish_events_immediately()

        # Return result
        return AgentExecutionResult(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            success=self.state.success,
            final_response=self.state.final_response or "No final response",
            total_cost=self.budget_tracker.cost if self.budget_tracker else 0.0,
            reasoning_iterations_used=self.state.current_iteration,
            conversation_history=self.state.messages
        )

    async def _handle_workflow_error(self, error: Exception) -> None:
        """Handle workflow-level errors."""
        if self.event_manager:
            self.event_manager.add_event(EventTypes.WORKFLOW_FAILED, {
                "error": str(error),
                "error_type": type(error).__name__,
                "iterations_completed": self.state.current_iteration
            })
            await self._publish_events_immediately()

    def _build_goal_from_request(self, request: AgentExecutionRequest) -> AgentGoal:
        """Build goal from execution request."""
        return AgentGoal(
            id=str(request.task_id),
            description=request.task_query,
            success_criteria=request.task_parameters.get("success_criteria", ["Task completed successfully"]),
            max_iterations=request.task_parameters.get("max_iterations", MAX_ITERATIONS),
            requires_human_approval=request.requires_human_approval,
            context=request.task_parameters
        )

    # Signal handlers for human interaction
    @workflow.signal
    async def pause(self, reason: str = "Manual pause") -> None:
        """Pause workflow execution."""
        self._paused = True
        self._pause_reason = reason
        workflow.logger.info(f"Workflow paused: {reason}")

    @workflow.signal
    async def resume(self, reason: str = "Manual resume") -> None:
        """Resume workflow execution."""
        self._paused = False
        self._pause_reason = ""
        workflow.logger.info(f"Workflow resumed: {reason}")

    # Query methods for external inspection
    @workflow.query
    def get_workflow_events(self) -> list[dict[str, Any]]:
        """Get all workflow events."""
        return self.event_manager.get_events() if self.event_manager else []

    @workflow.query
    def get_latest_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get latest workflow events."""
        return self.event_manager.get_latest_events(limit) if self.event_manager else []

    @workflow.query
    def get_current_state(self) -> dict[str, Any]:
        """Get current workflow state."""
        return {
            "status": self.state.status,
            "current_iteration": self.state.current_iteration,
            "success": self.state.success,
            "cost": self.budget_tracker.cost if self.budget_tracker else 0.0,
            "budget_remaining": self.budget_tracker.get_remaining() if self.budget_tracker else 0.0,
            "paused": self._paused,
            "pause_reason": self._pause_reason
        }
