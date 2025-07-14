from datetime import timedelta
from enum import Enum
from typing import Any, TypedDict

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

from ..models import AgentExecutionRequest, AgentExecutionResult


class Activities:
    """Activity function references to avoid hardcoded strings."""
    
    build_agent_config = "build_agent_config_activity"
    discover_available_tools = "discover_available_tools_activity" 
    call_llm = "call_llm_activity"
    execute_mcp_tool = "execute_mcp_tool_activity"
    create_execution_plan = "create_execution_plan_activity"
    evaluate_goal_progress = "evaluate_goal_progress_activity"


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

    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        """Main workflow execution with enhanced error handling and state management."""
        try:
            # Initialize execution state
            self.execution_id = str(workflow.uuid4())
            self._state = self._initialize_execution_state(request)

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
                try:
                    await self._execute_iteration()
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
                non_retryable=True
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

        # Add response to conversation
        response_message = {
            "id": str(workflow.uuid4()),
            "role": "assistant",
            "content": llm_response.get("content", ""),
            "timestamp": workflow.now().isoformat(),
            "tool_calls": llm_response.get("tool_calls", []),
            "metadata": {"iteration": self._state["current_iteration"]},
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
                non_retryable=True
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
