from datetime import timedelta
from enum import Enum
from typing import Any, TypedDict

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_common.config.settings import get_settings

from ..models import AgentExecutionRequest, AgentExecutionResult


class Activities:
    """Activity function references to avoid hardcoded strings."""

    build_agent_config = "build_agent_config_activity"
    discover_available_tools = "discover_available_tools_activity"
    call_llm = "call_llm_activity"
    execute_mcp_tool = "execute_mcp_tool_activity"
    create_execution_plan = "create_execution_plan_activity"
    evaluate_goal_progress = "evaluate_goal_progress_activity"
    publish_workflow_events = "publish_workflow_events_activity"


class ExecutionStatus(Enum):
    """Agent execution status."""

    INITIALIZING = "initializing"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    TOOL_EXECUTION = "tool_execution"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentGoal(TypedDict):
    """Represents an agent's goal with context and success criteria."""

    id: str
    description: str
    success_criteria: list[str]
    max_iterations: int
    requires_human_approval: bool
    context: dict[str, Any]


class AgentExecutionState(TypedDict):
    """Enhanced state management for agent execution."""

    # Core identifiers
    execution_id: str
    agent_id: str
    task_id: str

    # Goal and planning
    goal: AgentGoal
    plan: str | None
    current_step: int
    total_steps: int

    # Execution state
    status: str
    current_iteration: int
    messages: list[dict[str, Any]]

    # Agent configuration
    agent_config: dict[str, Any]
    available_tools: list[dict[str, Any]]

    # Execution tracking
    tool_calls_made: int
    errors_encountered: list[dict[str, Any]]

    # Human interaction
    pending_approval: dict[str, Any] | None
    approval_required: bool

    # Results
    final_response: str | None
    success: bool

    # Budget and cost tracking
    budget_usd: float | None
    budget_exceeded: bool


@workflow.defn
class AgentExecutionWorkflow:
    """Enhanced agent execution workflow following Temporal AI best practices.

    This workflow implements:
    - Goal-oriented agent execution
    - Human-in-the-loop capabilities via signals
    - Enhanced state management and conversation tracking
    - Robust error handling and retry policies
    - Real-time monitoring via queries
    """

    def __init__(self) -> None:
        self._state: AgentExecutionState | None = None
        self._is_paused: bool = False
        self._pause_reason: str = ""
        self.cost = 0
        self._events: list[dict[str, Any]] = []

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Main workflow execution with enhanced error handling and state management."""
        try:
            # Initialize execution state
            self.execution_id = str(workflow.uuid4())
            self._state = self._initialize_execution_state(request)

            # Store workflow started event
            self._add_event(
                "WorkflowStarted",
                {
                    "goal": request.task_query,
                    "budget_usd": self._state["budget_usd"] if self._state else None,
                },
            )

            # Build agent configuration with enhanced error handling
            agent_config = await workflow.execute_activity(
                Activities.build_agent_config,
                args=[request.agent_id],
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),
                    maximum_attempts=3,
                    backoff_coefficient=2.0,
                ),
            )

            # Discover available tools
            available_tools = await workflow.execute_activity(
                Activities.discover_available_tools,
                args=[request.agent_id],
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Update state with configuration
            if self._state:
                self._state["agent_config"] = agent_config
                self._state["available_tools"] = available_tools
                self._state["status"] = ExecutionStatus.PLANNING.value

            # Create execution plan
            await self._create_execution_plan()

            # Main execution loop with enhanced control flow
            while not self._should_terminate():
                # Check if workflow is paused
                if self._is_paused:
                    if self._state:
                        self._state["status"] = "paused"

                    # Wait for resume signal
                    def is_resumed() -> bool:
                        return not self._is_paused

                    await workflow.wait_condition(is_resumed)

                    # Update status when resumed
                    if self._state:
                        self._state["status"] = ExecutionStatus.EXECUTING.value

                try:
                    await self._execute_iteration()

                    # Publish events at end of each iteration (fire-and-forget)
                    await self._publish_pending_events()

                except ApplicationError:
                    # ApplicationErrors should bubble up to fail the workflow
                    raise
                except Exception as e:
                    await self._handle_execution_error(e)

                    # Check if we should continue after error
                    if self._state and self._state["status"] == ExecutionStatus.FAILED.value:
                        break

            # Finalize execution
            return self._finalize_execution()

        except Exception as e:
            workflow.logger.error(f"Agent execution failed: {e}")
            # For workflow failures, we should raise ApplicationError for proper handling
            raise ApplicationError(
                f"Agent execution failed: {e!s}",
                type="WorkflowExecutionFailure",
                non_retryable=True,
            )

    def _initialize_execution_state(self, request: AgentExecutionRequest) -> AgentExecutionState:
        """Initialize the execution state with goal-oriented structure."""
        goal = AgentGoal(
            id=f"goal_{request.task_id}",
            description=request.task_query,
            success_criteria=[
                "Task requirements are clearly understood",
                "All necessary information has been gathered",
                "Solution has been implemented or provided",
                "User confirmation received if required",
            ],
            max_iterations=request.max_reasoning_iterations or 10,
            requires_human_approval=request.requires_human_approval,
            context={"original_request": request.task_query},
        )

        initial_message = {
            "id": str(workflow.uuid4()),
            "role": "user",
            "content": request.task_query,
            "timestamp": workflow.now().isoformat(),
            "tool_calls": None,
            "metadata": {"source": "initial_request"},
        }

        return AgentExecutionState(
            execution_id=self.execution_id,
            agent_id=str(request.agent_id),
            task_id=str(request.task_id),
            goal=goal,
            plan=None,
            current_step=0,
            total_steps=0,
            status=ExecutionStatus.INITIALIZING.value,
            current_iteration=0,
            messages=[initial_message],
            agent_config={},
            available_tools=[],
            tool_calls_made=0,
            errors_encountered=[],
            pending_approval=None,
            approval_required=goal["requires_human_approval"],
            final_response=None,
            success=False,
            budget_usd=request.budget_usd or get_settings().task_execution.DEFAULT_TASK_BUDGET_USD,
            budget_exceeded=False,
        )

    async def _create_execution_plan(self) -> None:
        """Create an execution plan based on the goal and available tools."""
        if not self._state:
            return

        self._state["status"] = ExecutionStatus.PLANNING.value

        try:
            planning_result = await workflow.execute_activity(
                Activities.create_execution_plan,
                args=[self._state["goal"], self._state["available_tools"], self._state["messages"]],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            self._state["plan"] = planning_result.get("plan")
            self._state["total_steps"] = planning_result.get("estimated_steps", 5)
            self._state["status"] = ExecutionStatus.EXECUTING.value
        except Exception as e:
            workflow.logger.warning(f"Planning failed, proceeding with default plan: {e}")
            self._state["plan"] = f"Execute task: {self._state['goal']['description']}"
            self._state["total_steps"] = 5
            self._state["status"] = ExecutionStatus.EXECUTING.value

    async def _execute_iteration(self) -> None:
        """Execute a single iteration of the agent workflow."""
        if not self._state:
            return

        self._state["current_iteration"] += 1
        self._state["current_step"] += 1

        # LLM reasoning step
        llm_response = await self._llm_reasoning_step()

        # Check if human approval is needed
        if self._requires_approval(llm_response):
            await self._request_human_approval(llm_response)
            return

        # Tool execution if needed
        if self._has_tool_calls(llm_response):
            await self._execute_tools(llm_response)

        # Evaluate progress
        await self._evaluate_progress()

    async def _llm_reasoning_step(self) -> dict[str, Any]:
        """Enhanced LLM reasoning with better context and error handling."""
        if not self._state:
            return {}

        # Convert state messages to LLM format
        llm_messages: list[dict[str, Any]] = []
        for msg in self._state["messages"]:
            llm_messages.append(
                {
                    "role": msg["role"],
                    "content": msg["content"],
                    "tool_calls": msg.get("tool_calls"),
                }
            )

        # Add goal context to system message
        system_context = self._build_system_context()
        if llm_messages and llm_messages[0]["role"] == "system":
            llm_messages[0]["content"] += f"\n\n{system_context}"
        else:
            llm_messages.insert(0, {"role": "system", "content": system_context})

        # Check budget before making LLM call
        await self._check_budget_before_llm_call()

        # Store LLM call started event
        model_id = self._state["agent_config"].get("model_id", "unknown")
        estimated_cost = self._estimate_llm_call_cost()
        self._add_event(
            "WorkflowLLMCallStarted", {"model_id": model_id, "estimated_cost": estimated_cost}
        )

        llm_response = await workflow.execute_activity(
            Activities.call_llm,
            args=[
                llm_messages,
                self._state["agent_config"].get("model_id"),
                self._state["available_tools"],
            ],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=2),
                maximum_interval=timedelta(minutes=1),
                maximum_attempts=3,
                backoff_coefficient=2.0,
            ),
        )

        # Accumulate cost from LLM call
        if "cost" in llm_response:
            call_cost = llm_response.get("cost", 0.0)
            self.cost += call_cost
            workflow.logger.info(f"LLM call cost: ${call_cost:.6f}, total cost: ${self.cost:.6f}")

        # Store LLM call completed event
        self._add_event(
            "WorkflowLLMCallCompleted",
            {
                "content": llm_response.get("content", "")[:500],  # Truncate long content
                "cost": llm_response.get("cost", 0.0),
                "usage": llm_response.get("usage", {}),
                "tool_calls_count": len(llm_response.get("tool_calls", [])),
                "has_tool_calls": len(llm_response.get("tool_calls", [])) > 0,
            },
        )

        # Add response to conversation
        response_message = {
            "id": str(workflow.uuid4()),
            "role": "assistant",
            "content": llm_response.get("content", ""),
            "timestamp": workflow.now().isoformat(),
            "tool_calls": llm_response.get("tool_calls", []),
            "metadata": {
                "iteration": self._state["current_iteration"],
                "cost": llm_response.get("cost", 0.0),
                "usage": llm_response.get("usage", {}),
            },
        }

        self._state["messages"].append(response_message)
        return llm_response

    def _build_system_context(self) -> str:
        """Build enhanced system context with goal and progress information."""
        if not self._state:
            return "System context unavailable"

        goal = self._state["goal"]
        success_criteria = "\n".join(f"- {criteria}" for criteria in goal["success_criteria"])

        return f"""
AGENT GOAL: {goal["description"]}

SUCCESS CRITERIA:
{success_criteria}

EXECUTION CONTEXT:
- Current Step: {self._state["current_step"]}/{self._state["total_steps"]}
- Iteration: {self._state["current_iteration"]}/{goal["max_iterations"]}
- Tools Available: {len(self._state["available_tools"])}
- Plan: {self._state.get("plan", "No plan created yet")}

Remember to work systematically toward the goal and ask for human approval when making significant decisions.
"""

    def _requires_approval(self, llm_response: dict[str, Any]) -> bool:
        """Check if the current action requires human approval."""
        if not self._state or not self._state["approval_required"]:
            return False

        # Check for high-impact tool calls
        tool_calls = llm_response.get("tool_calls", [])
        high_impact_tools = ["execute_command", "write_file", "delete_file", "send_email"]

        return any(
            tool_call.get("function", {}).get("name") in high_impact_tools
            for tool_call in tool_calls
        )

    async def _request_human_approval(self, llm_response: dict[str, Any]) -> None:
        """Request human approval for the proposed action."""
        if not self._state:
            return

        self._state["status"] = ExecutionStatus.WAITING_FOR_APPROVAL.value
        self._state["pending_approval"] = {
            "action": llm_response,
            "timestamp": workflow.now().isoformat(),
            "iteration": self._state["current_iteration"],
        }

        # Wait for approval signal
        def approval_received() -> bool:
            return self._state is not None and self._state["pending_approval"] is None

        await workflow.wait_condition(
            approval_received,
            timeout=timedelta(hours=24),  # 24 hour timeout for approval
        )

    async def _execute_tools(self, llm_response: dict[str, Any]) -> None:
        """Execute tools with enhanced error handling and result tracking."""
        if not self._state:
            return

        self._state["status"] = ExecutionStatus.TOOL_EXECUTION.value
        tool_calls = llm_response.get("tool_calls", [])

        for tool_call in tool_calls:
            try:
                tool_result = await workflow.execute_activity(
                    Activities.execute_mcp_tool,
                    args=[
                        tool_call.get("function", {}).get("name", ""),
                        tool_call.get("function", {}).get("arguments", {}),
                        None,
                    ],
                    start_to_close_timeout=timedelta(minutes=3),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=30),
                        maximum_attempts=3,
                    ),
                )

                self._state["tool_calls_made"] += 1

                # Add tool result to conversation
                tool_message = {
                    "id": str(workflow.uuid4()),
                    "role": "tool",
                    "content": str(tool_result),
                    "timestamp": workflow.now().isoformat(),
                    "tool_calls": None,
                    "metadata": {
                        "tool_call_id": tool_call.get("id", ""),
                        "tool_name": tool_call.get("function", {}).get("name", ""),
                        "success": True,
                    },
                }
                self._state["messages"].append(tool_message)

            except Exception as e:
                workflow.logger.warning(f"Tool execution failed: {e}")

                # Add error to conversation
                error_message = {
                    "id": str(workflow.uuid4()),
                    "role": "tool",
                    "content": f"Error: {e!s}",
                    "timestamp": workflow.now().isoformat(),
                    "tool_calls": None,
                    "metadata": {
                        "tool_call_id": tool_call.get("id", ""),
                        "tool_name": tool_call.get("function", {}).get("name", ""),
                        "success": False,
                    },
                }
                self._state["messages"].append(error_message)

                self._state["errors_encountered"].append(
                    {
                        "type": "tool_execution_error",
                        "tool_name": tool_call.get("function", {}).get("name", ""),
                        "error": str(e),
                        "iteration": self._state["current_iteration"],
                    }
                )

    async def _evaluate_progress(self) -> None:
        """Evaluate progress toward the goal."""
        if not self._state:
            return

        self._state["status"] = ExecutionStatus.EVALUATING.value

        try:
            evaluation_result = await workflow.execute_activity(
                Activities.evaluate_goal_progress,
                args=[
                    self._state["goal"],
                    self._state["messages"],
                    self._state["current_iteration"],
                ],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            if evaluation_result.get("goal_achieved", False):
                self._state["status"] = ExecutionStatus.COMPLETED.value
                self._state["success"] = True
                self._state["final_response"] = evaluation_result.get(
                    "final_response", "Task completed successfully"
                )
            else:
                self._state["status"] = ExecutionStatus.EXECUTING.value
        except Exception as e:
            workflow.logger.warning(f"Goal evaluation failed, continuing: {e}")
            self._state["status"] = ExecutionStatus.EXECUTING.value

    async def _handle_execution_error(self, error: Exception) -> None:
        """Handle execution errors with recovery strategies using Temporal best practices."""
        if not self._state:
            return

        error_info = {
            "type": "execution_error",
            "error": str(error),
            "iteration": self._state["current_iteration"],
            "timestamp": workflow.now().isoformat(),
        }

        self._state["errors_encountered"].append(error_info)

        # Check if we should fail or continue
        if len(self._state["errors_encountered"]) >= 3:
            self._state["status"] = ExecutionStatus.FAILED.value
            self._state["final_response"] = f"Execution failed after multiple errors: {error!s}"

            # For critical failures after multiple attempts, raise ApplicationError
            # This will properly fail the workflow execution
            raise ApplicationError(
                f"Workflow execution failed after {len(self._state['errors_encountered'])} errors: {error!s}",
                type="CriticalExecutionFailure",
                non_retryable=True,
            )
        else:
            workflow.logger.warning(f"Execution error (continuing): {error}")

    def _should_terminate(self) -> bool:
        """Check if the workflow should terminate."""
        if not self._state:
            return True

        # Check if we've reached a terminal status
        if self._state["status"] in [
            ExecutionStatus.COMPLETED.value,
            ExecutionStatus.FAILED.value,
            ExecutionStatus.CANCELLED.value,
        ]:
            return True

        # Check if we've reached max iterations - if so, mark as completed
        if self._state["current_iteration"] >= self._state["goal"]["max_iterations"]:
            # If we've reached max iterations but haven't failed, consider it successful
            if self._state["status"] != ExecutionStatus.FAILED.value:
                self._state["status"] = ExecutionStatus.COMPLETED.value
                self._state["success"] = True
                if not self._state["final_response"]:
                    # Get the last assistant message as the final response
                    for message in reversed(self._state["messages"]):
                        if message["role"] == "assistant" and message["content"]:
                            self._state["final_response"] = message["content"]
                            break
                    if not self._state["final_response"]:
                        self._state["final_response"] = "Task completed after maximum iterations"
            return True

        return False

    def _has_tool_calls(self, llm_response: dict[str, Any]) -> bool:
        """Check if the LLM response contains tool calls."""
        tool_calls = llm_response.get("tool_calls", [])
        return len(tool_calls) > 0

    async def _check_budget_before_llm_call(self) -> None:
        """Check if budget allows for the next LLM call before making it."""
        if not self._state or not self._state["budget_usd"]:
            return  # No budget limit set

        budget_limit = self._state["budget_usd"]
        current_cost = self.cost

        # Estimate cost for upcoming LLM call based on context
        estimated_call_cost = self._estimate_llm_call_cost()
        projected_total = current_cost + estimated_call_cost

        # Check if projected cost would exceed budget
        if projected_total >= budget_limit:
            workflow.logger.warning(
                f"Projected cost would exceed budget: ${projected_total:.6f} >= ${budget_limit:.6f}"
            )
            self._state["budget_exceeded"] = True

            # Pause workflow for budget approval
            self._is_paused = True
            self._pause_reason = (
                f"Budget would be exceeded by next LLM call. Current: ${current_cost:.6f}, "
                f"Estimated call: ${estimated_call_cost:.6f}, Budget: ${budget_limit:.6f}"
            )
            self._state["status"] = "paused_budget_would_exceed"

            # Add budget would exceed message to conversation
            budget_message = {
                "id": str(workflow.uuid4()),
                "role": "system",
                "content": (
                    f"Next LLM call would exceed budget limit of ${budget_limit:.2f}. "
                    f"Current cost: ${current_cost:.6f}, Estimated call cost: ${estimated_call_cost:.6f}. "
                    f"Workflow paused pending budget approval."
                ),
                "timestamp": workflow.now().isoformat(),
                "tool_calls": None,
                "metadata": {
                    "type": "budget_would_exceed",
                    "budget_limit": budget_limit,
                    "current_cost": current_cost,
                    "estimated_call_cost": estimated_call_cost,
                    "projected_total": projected_total,
                },
            }
            self._state["messages"].append(budget_message)

            # Wait for either budget update or explicit approval to continue
            def budget_allows_continuation() -> bool:
                if not self._state or not self._state["budget_usd"]:
                    return False
                # Check if budget was increased or if we're explicitly resumed
                return not self._is_paused or (
                    self.cost + estimated_call_cost < self._state["budget_usd"]
                )

            await workflow.wait_condition(budget_allows_continuation)

        # Check if approaching budget limit (within safety margin)
        elif budget_limit > 0:
            safety_margin = budget_limit * 0.1  # 10% safety margin by default
            if projected_total >= (budget_limit - safety_margin):
                remaining = budget_limit - projected_total
                workflow.logger.warning(
                    f"Next call would approach budget limit. Remaining after call: ${remaining:.6f}"
                )

                # Add warning message
                warning_message = {
                    "id": str(workflow.uuid4()),
                    "role": "system",
                    "content": (
                        f"Warning: Next LLM call will approach budget limit. "
                        f"Remaining after call: ${remaining:.6f} of ${budget_limit:.2f}"
                    ),
                    "timestamp": workflow.now().isoformat(),
                    "tool_calls": None,
                    "metadata": {
                        "type": "budget_approaching_warning",
                        "budget_limit": budget_limit,
                        "current_cost": current_cost,
                        "estimated_call_cost": estimated_call_cost,
                        "projected_remaining": remaining,
                    },
                }
                self._state["messages"].append(warning_message)

    def _estimate_llm_call_cost(self) -> float:
        """Estimate the cost of the upcoming LLM call based on context."""
        if not self._state:
            return 0.0

        # Get recent messages to estimate token count
        recent_messages = self._state["messages"][-5:]  # Last 5 messages for context
        total_chars = sum(len(msg.get("content", "")) for msg in recent_messages)

        # Rough estimation: 1 token ≈ 4 characters, with system context
        estimated_prompt_tokens = (total_chars // 4) + 500  # +500 for system context
        estimated_completion_tokens = 300  # Conservative estimate for response
        estimated_total_tokens = estimated_prompt_tokens + estimated_completion_tokens

        # Conservative cost estimate: $0.02 per 1K tokens (high-end pricing)
        estimated_cost = (estimated_total_tokens / 1000) * 0.02

        # Add 50% safety margin to be conservative
        return estimated_cost * 1.5

    async def _check_budget_limits(self) -> None:
        """Check if budget limits have been exceeded and handle accordingly."""
        if not self._state or not self._state["budget_usd"]:
            return  # No budget limit set

        budget_limit = self._state["budget_usd"]
        current_cost = self.cost

        # Check if budget is exceeded
        if current_cost >= budget_limit:
            workflow.logger.warning(f"Budget exceeded: ${current_cost:.6f} >= ${budget_limit:.6f}")
            self._state["budget_exceeded"] = True

            # Pause workflow for budget approval
            self._is_paused = True
            self._pause_reason = (
                f"Budget exceeded: ${current_cost:.6f} of ${budget_limit:.6f} spent"
            )
            self._state["status"] = "paused_budget_exceeded"

            # Add budget exceeded message to conversation
            budget_message = {
                "id": str(workflow.uuid4()),
                "role": "system",
                "content": f"Budget limit of ${budget_limit:.2f} has been exceeded. Current cost: ${current_cost:.6f}. Workflow paused pending approval.",
                "timestamp": workflow.now().isoformat(),
                "tool_calls": None,
                "metadata": {
                    "type": "budget_exceeded",
                    "budget_limit": budget_limit,
                    "current_cost": current_cost,
                },
            }
            self._state["messages"].append(budget_message)

        # Check if approaching budget limit (within safety margin)
        elif budget_limit > 0:
            safety_margin = budget_limit * 0.1  # 10% safety margin by default
            if current_cost >= (budget_limit - safety_margin):
                remaining = budget_limit - current_cost
                workflow.logger.warning(f"Approaching budget limit. Remaining: ${remaining:.6f}")

                # Add warning message
                warning_message = {
                    "id": str(workflow.uuid4()),
                    "role": "system",
                    "content": f"Warning: Approaching budget limit. Remaining: ${remaining:.6f} of ${budget_limit:.2f}",
                    "timestamp": workflow.now().isoformat(),
                    "tool_calls": None,
                    "metadata": {
                        "type": "budget_warning",
                        "budget_limit": budget_limit,
                        "current_cost": current_cost,
                        "remaining": remaining,
                    },
                }
                self._state["messages"].append(warning_message)

    def _finalize_execution(self) -> AgentExecutionResult:
        """Finalize the execution and return results."""
        if not self._state:
            return AgentExecutionResult(
                task_id=UUID("00000000-0000-0000-0000-000000000000"),
                agent_id=UUID("00000000-0000-0000-0000-000000000000"),
                success=False,
                final_response="Execution state unavailable",
                conversation_history=[],
                total_tool_calls=0,
                reasoning_iterations_used=0,
                error_message="State was None during finalization",
                total_cost=self.cost,
            )

        if not self._state["final_response"]:
            # Extract final response from last assistant message
            for message in reversed(self._state["messages"]):
                if message["role"] == "assistant" and message["content"]:
                    self._state["final_response"] = message["content"]
                    break

            if not self._state["final_response"]:
                self._state["final_response"] = "Task execution completed"

        return AgentExecutionResult(
            task_id=UUID(self._state["task_id"]),
            agent_id=UUID(self._state["agent_id"]),
            success=self._state["success"],
            final_response=self._state["final_response"],
            conversation_history=self._state["messages"],
            total_tool_calls=self._state["tool_calls_made"],
            reasoning_iterations_used=self._state["current_iteration"],
            error_message=None if self._state["success"] else "Execution completed with errors",
            total_cost=self.cost,
        )

    # Signal handlers for human-in-the-loop
    @workflow.signal
    async def approve_action(self, approved: bool, feedback: str = "") -> None:
        """Handle human approval signal."""
        if not self._state or not self._state["pending_approval"]:
            return

        if approved:
            # Clear pending approval to continue execution
            self._state["pending_approval"] = None
            self._state["status"] = ExecutionStatus.EXECUTING.value

            if feedback:
                feedback_message = {
                    "id": str(workflow.uuid4()),
                    "role": "user",
                    "content": f"Approved with feedback: {feedback}",
                    "timestamp": workflow.now().isoformat(),
                    "tool_calls": None,
                    "metadata": {"type": "approval_feedback"},
                }
                self._state["messages"].append(feedback_message)
        else:
            # Rejection - ask for new approach
            self._state["pending_approval"] = None
            self._state["status"] = ExecutionStatus.EXECUTING.value

            rejection_message = {
                "id": str(workflow.uuid4()),
                "role": "user",
                "content": f"Action rejected. Please try a different approach. Feedback: {feedback}",
                "timestamp": workflow.now().isoformat(),
                "tool_calls": None,
                "metadata": {"type": "rejection_feedback"},
            }
            self._state["messages"].append(rejection_message)

    @workflow.signal
    async def cancel_execution(self, reason: str = "") -> None:
        """Handle execution cancellation signal."""
        if not self._state:
            return

        self._state["status"] = ExecutionStatus.CANCELLED.value
        self._state["final_response"] = f"Execution cancelled: {reason}"

    @workflow.signal
    async def provide_feedback(self, feedback: str) -> None:
        """Handle additional feedback from human."""
        if not self._state:
            return

        feedback_message = {
            "id": str(workflow.uuid4()),
            "role": "user",
            "content": feedback,
            "timestamp": workflow.now().isoformat(),
            "tool_calls": None,
            "metadata": {"type": "human_feedback"},
        }
        self._state["messages"].append(feedback_message)

    @workflow.signal
    async def pause_execution(self, reason: str = "") -> None:
        """Handle execution pause signal."""
        self._is_paused = True
        self._pause_reason = reason
        workflow.logger.info(f"Workflow paused: {reason}")

    @workflow.signal
    async def resume_execution(self, reason: str = "") -> None:
        """Handle execution resume signal."""
        self._is_paused = False
        self._pause_reason = ""
        workflow.logger.info(f"Workflow resumed: {reason}")

    @workflow.signal
    async def update_budget(self, new_budget_usd: float, reason: str = "") -> None:
        """Handle budget update signal."""
        if not self._state:
            return

        old_budget = self._state["budget_usd"]
        self._state["budget_usd"] = new_budget_usd

        # If budget was exceeded but new budget covers current cost, resume execution
        if self._state["budget_exceeded"] and self.cost < new_budget_usd:
            self._state["budget_exceeded"] = False
            if self._is_paused and "budget" in self._pause_reason.lower():
                self._is_paused = False
                self._pause_reason = ""

        # Add budget update message
        budget_update_message = {
            "id": str(workflow.uuid4()),
            "role": "system",
            "content": f"Budget updated from ${old_budget:.2f} to ${new_budget_usd:.2f}. {reason}",
            "timestamp": workflow.now().isoformat(),
            "tool_calls": None,
            "metadata": {
                "type": "budget_updated",
                "old_budget": old_budget,
                "new_budget": new_budget_usd,
                "current_cost": self.cost,
            },
        }
        self._state["messages"].append(budget_update_message)

        workflow.logger.info(
            f"Budget updated from ${old_budget:.2f} to ${new_budget_usd:.2f}: {reason}"
        )

    # Query handlers for monitoring
    @workflow.query
    def get_execution_status(self) -> dict[str, Any]:
        """Get current execution status for monitoring."""
        if not self._state:
            return {"status": "not_initialized"}

        return {
            "execution_id": self._state["execution_id"],
            "status": self._state["status"],
            "current_iteration": self._state["current_iteration"],
            "max_iterations": self._state["goal"]["max_iterations"],
            "current_step": self._state["current_step"],
            "total_steps": self._state["total_steps"],
            "tool_calls_made": self._state["tool_calls_made"],
            "errors_count": len(self._state["errors_encountered"]),
            "goal_description": self._state["goal"]["description"],
            "requires_approval": self._state["approval_required"],
            "pending_approval": self._state["pending_approval"] is not None,
            "is_paused": self._is_paused,
            "pause_reason": self._pause_reason,
            "budget_usd": self._state["budget_usd"],
            "current_cost": self.cost,
            "budget_exceeded": self._state["budget_exceeded"],
            "budget_remaining": (self._state["budget_usd"] - self.cost)
            if self._state["budget_usd"]
            else None,
        }

    @workflow.query
    def get_conversation_history(self) -> list[dict[str, Any]]:
        """Get current conversation history."""
        return self._state["messages"] if self._state else []

    @workflow.query
    def get_goal_progress(self) -> dict[str, Any]:
        """Get goal progress information."""
        if not self._state:
            return {}

        progress_percentage = 0
        if self._state["total_steps"] > 0:
            progress_percentage = min(
                100, (self._state["current_step"] / self._state["total_steps"]) * 100
            )

        return {
            "goal": self._state["goal"],
            "plan": self._state["plan"],
            "progress_percentage": progress_percentage,
            "success_criteria_met": [],  # Could be enhanced with actual tracking
        }

    @workflow.query
    def get_error_history(self) -> list[dict[str, Any]]:
        """Get error history for debugging."""
        return self._state["errors_encountered"] if self._state else []

    @workflow.query
    def get_budget_status(self) -> dict[str, Any]:
        """Get detailed budget and cost information."""
        if not self._state:
            return {}

        budget_limit = self._state["budget_usd"]
        current_cost = self.cost

        result = {
            "budget_limit_usd": budget_limit,
            "current_cost_usd": current_cost,
            "budget_exceeded": self._state["budget_exceeded"],
            "budget_remaining_usd": (budget_limit - current_cost) if budget_limit else None,
            "budget_utilization_percent": (current_cost / budget_limit * 100)
            if budget_limit and budget_limit > 0
            else 0,
        }

        # Add cost breakdown by LLM calls
        llm_costs = []
        for message in self._state["messages"]:
            if message.get("role") == "assistant" and "cost" in message.get("metadata", {}):
                llm_costs.append(
                    {
                        "iteration": message["metadata"].get("iteration", 0),
                        "cost": message["metadata"]["cost"],
                        "usage": message["metadata"].get("usage", {}),
                        "timestamp": message["timestamp"],
                    }
                )

        result["cost_breakdown"] = llm_costs
        return result

    def _add_event(self, event_type: str, data: dict[str, Any]):
        """Add an event to the workflow event log for external consumption."""
        if self._state:
            event = {
                "event_id": str(workflow.uuid4()),
                "event_type": event_type,
                "timestamp": workflow.now().isoformat(),
                "execution_id": self.execution_id,
                "task_id": self._state["task_id"],
                "agent_id": self._state["agent_id"],
                "data": data,
            }
            self._events.append(event)
            workflow.logger.debug(f"Added workflow event: {event_type}")

    async def _publish_pending_events(self):
        """Publish all pending events to event broker (fire-and-forget)."""
        if not self._events:
            return

        try:
            # Use side effect to publish events without blocking workflow
            workflow.logger.info(f"Publishing {len(self._events)} workflow events")

            # Use short activity to publish events (simple approach)
            import json
            events_json = [json.dumps(event) for event in self._events]
            
            # Start activity with short timeout to publish events
            await workflow.execute_activity(
                Activities.publish_workflow_events,
                events_json,
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=1)  # Don't retry event publishing
            )

        except Exception as e:
            workflow.logger.warning(f"Failed to publish workflow events: {e}")
            # Don't fail workflow for event publishing issues
        
        # Clear published events
        self._events.clear()

    @workflow.query
    def get_workflow_events(self) -> list[dict[str, Any]]:
        """Get all workflow events for external consumption."""
        return self._events

    @workflow.query
    def get_latest_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the latest workflow events."""
        return self._events[-limit:] if self._events else []
