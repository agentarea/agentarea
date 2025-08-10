import json
from dataclasses import dataclass, field
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from ..message_types.messages import (
        Message,  # Legacy compatibility
        )
    from .helpers import (
        BudgetTracker,
        EventManager,
        MessageBuilder,
        StateValidator,
        ToolCallExtractor,
    )

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
class Message:
    """Structured message for conversation history."""
    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    function_call: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class ToolCall:
    """Structured tool call information."""
    id: str
    function: dict[str, Any]
    type: str = "function"


@dataclass
class ToolResult:
    """Result from tool execution."""
    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None


@dataclass
class LLMResponse:
    """Structured LLM response."""
    message: Message
    usage: dict[str, Any] | None = None
    cost: float = 0.0


@dataclass
class WorkflowEvent:
    """Structured workflow event."""
    event_type: str
    data: dict[str, Any]
    timestamp: str | None = None
    iteration: int | None = None


@dataclass
class ExecutionResult:
    """Result from main execution loop."""
    iterations_completed: int
    success: bool
    final_response: str | None = None
    total_cost: float = 0.0


@dataclass
class AgentExecutionState:
    """Simplified execution state with direct attribute access."""
    execution_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    user_id: str = ""  # Add user_id field for user context
    goal: AgentGoal | None = None
    status: str = ExecutionStatus.INITIALIZING
    current_iteration: int = 0
    messages: list[Message] = field(default_factory=list)
    agent_config: dict[str, Any] = field(default_factory=dict)
    available_tools: list[dict[str, Any]] = field(default_factory=list)
    final_response: str | None = None
    success: bool = False
    budget_usd: float | None = None
    user_context_data: dict[str, Any] = field(default_factory=dict)


@workflow.defn
class AgentExecutionWorkflow:
    """Agent execution workflow without ADK dependency."""

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
        self.state.user_id = request.user_id  # Add user_id from request
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

        # Prepare user context data for activities (simplified - no roles)
        self.state.user_context_data = {
            "user_id": "dev-user",  # Use dev-user as set by JWT handler in dev mode
            "workspace_id": "system"  # Use system workspace where agents are created
        }

        # Build agent config
        self.state.agent_config = await workflow.execute_activity(
            Activities.BUILD_AGENT_CONFIG,
            args=[UUID(self.state.agent_id), self.state.user_context_data],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
        )

        # Validate configuration
        if not StateValidator.validate_agent_config(self.state.agent_config):
            raise ApplicationError("Invalid agent configuration")

        # Discover available tools
        self.state.available_tools = await workflow.execute_activity(
            Activities.DISCOVER_AVAILABLE_TOOLS,
            args=[UUID(self.state.agent_id), self.state.user_context_data],
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
        # Debug logging
        workflow.logger.info(f"Checking termination conditions - success: {self.state.success} (type: {type(self.state.success)}), iteration: {self.state.current_iteration}")
        workflow.logger.info(f"State object id: {id(self.state)}")

        # Check if goal is achieved (highest priority)
        if self.state.success:
            workflow.logger.info("Goal achieved - terminating workflow")
            return False, "Goal achieved successfully"

        # Check maximum iterations
        max_iterations = self.state.goal.max_iterations if self.state.goal else MAX_ITERATIONS
        if self.state.current_iteration >= max_iterations:
            workflow.logger.info(f"Max iterations reached ({max_iterations}) - terminating workflow")
            return False, f"Maximum iterations reached ({max_iterations})"

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            workflow.logger.info("Budget exceeded - terminating workflow")
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
            await self._execute_traditional_iteration()

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

    async def _execute_traditional_iteration(self) -> None:
        """Execute iteration using traditional LLM + tool approach."""
        iteration = self.state.current_iteration

                # Build system prompt with agent context and current task
        if self.state.goal:
            system_prompt = MessageBuilder.build_system_prompt(
                agent_name=self.state.agent_config.get("name", "AI Agent"),
                agent_instruction=self.state.agent_config.get("instruction", "You are a helpful AI assistant."),
                goal_description=self.state.goal.description,
                success_criteria=self.state.goal.success_criteria,
                available_tools=self.state.available_tools
            )

            # Add system message if first iteration
            if iteration == 1:
                # Create Message directly instead of using from_base_message
                self.state.messages.append(Message(
                    role="system",
                    content=system_prompt
                ))
            else:
                # Add status update for subsequent iterations (not in system prompt)
                # Avoid importing PromptBuilder to prevent Temporal sandbox issues
                status_msg = f"Iteration {iteration}/{self.state.goal.max_iterations} | Budget remaining: ${self.budget_tracker.get_remaining():.2f}"
                # Status updates are just regular user messages in conversation context
                self.state.messages.append(Message(
                    role="user",
                    content=f"Status: {status_msg}"
                ))

        # Call LLM
        llm_response = await self._call_llm()

        # Process LLM response
        await self._process_llm_response(llm_response)

    async def _call_llm(self) -> LLMResponse:
        """Call LLM with current messages."""
        self.event_manager.add_event(EventTypes.LLM_CALL_STARTED, {
            "iteration": self.state.current_iteration,
            "message_count": len(self.state.messages)
        })
        await self._publish_events_immediately()

        try:
            # Convert messages to dict format for activity
            messages_dict = [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                    "function_call": msg.function_call
                }
                for msg in self.state.messages
            ]

            response = await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[
                    messages_dict,
                    self.state.agent_config.get("model_id"),
                    self.state.available_tools,
                    self.state.user_context_data["workspace_id"],  # workspace_id
                    self.state.user_context_data,  # user_context_data (deprecated but still passed)
                    None,  # temperature
                    None,  # max_tokens
                    self.state.task_id,  # task_id for event publishing
                    self.state.agent_id,  # agent_id for event publishing
                    self.state.execution_id,  # execution_id for event publishing
                    # Removed enable_streaming parameter - streaming is now always enabled
                ],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
            )

            # Extract usage info and update budget
            usage_info = {
                "cost": response.get("cost", 0.0),
                "usage": response.get("usage", {})
            }
            self.budget_tracker.add_cost(usage_info["cost"])

            self.event_manager.add_event(EventTypes.LLM_CALL_COMPLETED, {
                "iteration": self.state.current_iteration,
                "cost": usage_info["cost"],
                "total_cost": self.budget_tracker.cost,
                "usage": usage_info,
                "content": response.get("content", ""),
                "tool_calls": response.get("tool_calls", []),
                "role": response.get("role", "assistant")
            })
            await self._publish_events_immediately()

            # Convert response to LLMResponse data class
            # The response is directly from the activity, not nested in "message"
            message = Message(
                role=response.get("role", "assistant"),
                content=response.get("content", ""),
                tool_call_id=response.get("tool_call_id"),
                name=response.get("name"),
                function_call=response.get("function_call"),
                tool_calls=response.get("tool_calls")
            )

            return LLMResponse(
                message=message,
                usage=usage_info,
                cost=usage_info.get("cost", 0.0)
            )

        except Exception as e:
            # Simplified error handling - enriched error events are now published by the activity
            error_type = getattr(e, 'type', type(e).__name__)
            error_message = str(e)

            # Generic LLM error event for workflow tracking
            self.event_manager.add_event(EventTypes.LLM_CALL_FAILED, {
                "iteration": self.state.current_iteration,
                "error": error_message,
                "error_type": error_type,
                "model_id": self.state.agent_config.get("model_id")
            })

            await self._publish_events_immediately()
            raise

    async def _process_llm_response(self, response: LLMResponse) -> None:
        """Process LLM response and handle tool calls."""
        # Only add non-empty messages to state
        if response.message.content.strip() or response.message.tool_calls:
            # Create Message directly
            self.state.messages.append(Message(
                role="assistant",
                content=response.message.content,
                tool_calls=response.message.tool_calls
            ))
        else:
            workflow.logger.warning(f"Received empty LLM response in iteration {self.state.current_iteration}")

        # Extract and execute tool calls
        tool_calls = ToolCallExtractor.extract_tool_calls(response.message)

        # Handle the case where we have tool calls but no text content
        # This addresses the issue where LLM returns only tool calls without reasoning text
        if tool_calls and not response.message.content.strip():
            workflow.logger.info(f"LLM returned tool calls without text content in iteration {self.state.current_iteration}")

            # For task_complete tool, extract reasoning from the tool arguments
            task_complete_calls = [tc for tc in tool_calls if tc.function.get("name") == "task_complete"]
            if task_complete_calls:
                import json
                try:
                    # Try to extract reasoning content from task_complete arguments
                    tool_args = json.loads(task_complete_calls[0].function.get("arguments", "{}"))
                    reasoning_content = ""

                    # Look for common reasoning fields in task_complete arguments
                    for key in ["result", "reasoning", "explanation", "summary", "response"]:
                        if key in tool_args:
                            reasoning_content = str(tool_args[key])
                            break

                    if reasoning_content:
                        # Add content to the assistant message for better UX
                        workflow.logger.info("Extracting reasoning from task_complete arguments")
                        if self.state.messages:
                            # Update the last assistant message to include the extracted reasoning
                            last_message = self.state.messages[-1]
                            if last_message.role == "assistant" and not last_message.content.strip():
                                # Create a new message with the extracted content
                                self.state.messages[-1] = Message(
                                    role="assistant",
                                    content=reasoning_content,
                                    tool_calls=last_message.tool_calls
                                )
                                workflow.logger.info("Updated assistant message with extracted reasoning content")

                except (json.JSONDecodeError, KeyError, AttributeError) as e:
                    workflow.logger.debug(f"Could not extract reasoning from task_complete arguments: {e}")

        if tool_calls:
            await self._execute_tool_calls(tool_calls)
        elif not response.message.content.strip():
            # If we have no content and no tool calls, this is problematic
            workflow.logger.error(f"LLM returned empty response with no tool calls in iteration {self.state.current_iteration}")

        # Check if goal is achieved
        await self._evaluate_goal_progress()

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """Execute all tool calls from LLM response."""
        for tool_call in tool_calls:
            tool_name = tool_call.function["name"]

            # Parse arguments first to include them in the event
            import json
            try:
                tool_args = json.loads(tool_call.function["arguments"])
            except (json.JSONDecodeError, KeyError):
                tool_args = {}

            # Don't publish tool_call_started events for task_complete
            if tool_name != "task_complete":
                self.event_manager.add_event(EventTypes.TOOL_CALL_STARTED, {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                    "arguments": tool_args
                })
                await self._publish_events_immediately()
            else:
                workflow.logger.debug("task_complete tool started - not publishing as workflow event")

            try:

                # Execute tool call
                result = await workflow.execute_activity(
                    Activities.EXECUTE_MCP_TOOL,
                    args=[
                        tool_name,
                        tool_args
                    ],
                    start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS)
                )

                # Add tool result to messages (only for non-completion tools)
                # For task_complete, we don't need to add it to conversation since workflow will terminate
                if tool_name != "task_complete":
                    self.state.messages.append(Message(
                        role="tool",
                        content=str(result.get("result", "")),
                        tool_call_id=tool_call.id,
                        name=tool_name
                    ))

                # Check if this was a completion tool call
                workflow.logger.info(f"Tool '{tool_name}' executed with result: {result}")
                if tool_name == "task_complete":
                    workflow.logger.info(f"task_complete called - full result: {result}")
                    workflow.logger.info(f"result type: {type(result)}")
                    workflow.logger.info(f"result.get('success'): {result.get('success')}")
                    workflow.logger.info(f"result.get('completed'): {result.get('completed')}")

                    # Check both 'success' and 'completed' fields for completion
                    is_successful = result.get("success", False) or result.get("completed", False)
                    workflow.logger.info(f"is_successful: {is_successful}")

                    if is_successful:
                        self.state.success = True
                        self.state.final_response = result.get("result", "Task completed")
                        workflow.logger.info(f"Task completed successfully: {self.state.final_response}")
                        workflow.logger.info(f"Setting self.state.success = {self.state.success}")

                        # Log completion internally for debugging but don't publish as workflow event
                        workflow.logger.info(f"INTERNAL: Task completion detected - agent called task_complete with result: {self.state.final_response}")

                        # CRITICAL: Break out of tool execution loop immediately after successful task_complete
                        # This prevents the workflow from continuing to next iteration
                        workflow.logger.info("SUCCESS: Breaking from tool execution - task completed successfully")
                        return  # Exit the entire _execute_tool_calls method immediately
                    else:
                        workflow.logger.warning(f"task_complete called but not successful: {result}")

                    # Don't publish task_complete as a workflow event - it's handled internally
                    # The workflow completion will be signaled through workflow status events instead
                    workflow.logger.debug("task_complete tool executed - not publishing as workflow event")
                else:
                    # Only publish tool events for non-completion tools
                    self.event_manager.add_event(EventTypes.TOOL_CALL_COMPLETED, {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "success": result.get("success", False),
                        "iteration": self.state.current_iteration,
                        "result": result.get("result", ""),
                        "arguments": tool_args,
                        "execution_time": result.get("execution_time", "")
                    })
                    await self._publish_events_immediately()

            except Exception as e:
                workflow.logger.error(f"Tool call {tool_name} failed: {e}")

                # Add error message
                self.state.messages.append(Message(
                    role="tool",
                    content=f"Tool execution failed: {e}",
                    tool_call_id=tool_call.id,
                    name=tool_name
                ))

                # Don't publish tool_call_failed events for task_complete
                if tool_name != "task_complete":
                    self.event_manager.add_event(EventTypes.TOOL_CALL_FAILED, {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "error": str(e),
                        "iteration": self.state.current_iteration
                    })
                    await self._publish_events_immediately()
                else:
                    workflow.logger.debug("task_complete tool failed - not publishing as workflow event")

    async def _evaluate_goal_progress(self) -> None:
        """Evaluate if the goal has been achieved."""
        try:
            # If task_complete was already called successfully, don't override it
            if self.state.success:
                workflow.logger.info("Goal already marked as achieved by task_complete tool - skipping evaluation")
                return

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

                # Only update success if it wasn't already set by task_complete
                if not self.state.success:
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
