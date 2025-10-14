import json
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from .helpers import (
        BudgetTracker,
        EventManager,
        MessageBuilder,
        StateValidator,
        ToolCallExtractor,
    )
    from .models import (
        AgentExecutionState,
        AgentGoal,
        Message,
        ToolCall,
    )

from ..models import (
    AgentConfigRequest,
    AgentConfigResult,
    AgentExecutionRequest,
    AgentExecutionResult,
    LLMCallRequest,
    LLMCallResult,
    MCPToolRequest,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
    WorkflowEventsRequest,
)
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
        self.state.user_id = request.user_id
        self.state.workspace_id = request.workspace_id  # Add workspace_id from request
        self.state.goal = self._build_goal_from_request(request)
        self.state.status = ExecutionStatus.INITIALIZING
        self.state.budget_usd = request.budget_usd

        # Initialize helpers
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id,
        )
        self.budget_tracker = BudgetTracker(self.state.budget_usd)

        # Add workflow started event
        self.event_manager.add_event(
            EventTypes.WORKFLOW_STARTED,
            {
                "goal_description": self.state.goal.description,
                "max_iterations": self.state.goal.max_iterations,
                "budget_limit": self.budget_tracker.budget_limit,
            },
        )

        # Publish immediately
        await self._publish_events_immediately()

        # Initialize agent configuration
        await self._initialize_agent_config()

    async def _initialize_agent_config(self) -> None:
        """Initialize agent configuration and available tools."""
        workflow.logger.info("Initializing agent configuration")

        # Prepare user context data for activities
        # Use actual user_id and workspace_id from the request
        self.state.user_context_data = {
            "user_id": self.state.user_id,
            "workspace_id": self.state.workspace_id,
        }

        # Build agent config using Pydantic request model
        agent_config_request = AgentConfigRequest(
            agent_id=UUID(self.state.agent_id), user_context_data=self.state.user_context_data
        )
        agent_config_result: AgentConfigResult = await workflow.execute_activity(
            Activities.BUILD_AGENT_CONFIG,
            args=[agent_config_request],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        # Convert result to dict for state storage (supports Pydantic BaseModel or plain dict)
        try:
            self.state.agent_config = agent_config_result.model_dump()
        except AttributeError:
            self.state.agent_config = dict(agent_config_result)

        # Validate configuration
        if not StateValidator.validate_agent_config(self.state.agent_config):
            raise ApplicationError("Invalid agent configuration")

        # Discover available tools using Pydantic request model
        tools_request = ToolDiscoveryRequest(
            agent_id=UUID(self.state.agent_id), user_context_data=self.state.user_context_data
        )
        tools_result: ToolDiscoveryResult = await workflow.execute_activity(
            Activities.DISCOVER_AVAILABLE_TOOLS,
            args=[tools_request],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        # Normalize tools to list[dict] for state storage, accepting multiple shapes
        available_tools: list[dict[str, Any]] = []
        try:
            tools_list = tools_result.tools  # Expected ToolDiscoveryResult
        except AttributeError:
            tools_list = tools_result  # Fallback: activity returned a raw list

        for tool in tools_list or []:
            try:
                available_tools.append(tool.model_dump())  # Pydantic ToolDefinition
            except AttributeError:
                if isinstance(tool, dict):
                    available_tools.append(tool)
                else:
                    # Last resort: convert object to dict via __dict__
                    try:
                        available_tools.append(dict(tool.__dict__))
                    except Exception:  # noqa: S110
                        pass

        self.state.available_tools = available_tools

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
                workflow.logger.info(
                    f"Stopping execution before iteration {self.state.current_iteration}: {reason}"
                )
                # Decrement since we didn't actually execute this iteration
                self.state.current_iteration -= 1
                break

            workflow.logger.info(f"Starting iteration {self.state.current_iteration}")

            # Execute iteration
            await self._execute_iteration()

            # Check if we should finish after completing the iteration
            should_continue, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(
                    f"Stopping execution after iteration {self.state.current_iteration}: {reason}"
                )
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
        workflow.logger.info(
            f"Checking termination conditions - success: {self.state.success} (type: {type(self.state.success)}), iteration: {self.state.current_iteration}"
        )
        workflow.logger.info(f"State object id: {id(self.state)}")

        # Check if goal is achieved (highest priority)
        if self.state.success:
            workflow.logger.info("Goal achieved - terminating workflow")
            return False, "Goal achieved successfully"

        # Check maximum iterations
        max_iterations = self.state.goal.max_iterations if self.state.goal else MAX_ITERATIONS
        if self.state.current_iteration >= max_iterations:
            workflow.logger.info(
                f"Max iterations reached ({max_iterations}) - terminating workflow"
            )
            return False, f"Maximum iterations reached ({max_iterations})"

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            workflow.logger.info("Budget exceeded - terminating workflow")
            return (
                False,
                f"Budget exceeded (${self.budget_tracker.cost:.2f}/${self.budget_tracker.budget_limit:.2f})",
            )

        # Check for cancellation (this could be extended for other cancellation conditions)
        # For now, we don't have explicit cancellation, but this is where it would go

        # If we get here, execution should continue
        return True, "Continue execution"

    async def _execute_iteration(self) -> None:
        """Execute a single iteration."""
        iteration = self.state.current_iteration

        self.event_manager.add_event(
            EventTypes.ITERATION_STARTED,
            {
                "iteration": iteration,
                "budget_remaining": self.budget_tracker.get_remaining(),
            },
        )
        await self._publish_events_immediately()

        try:
            await self._execute_traditional_iteration()

            # Check budget warnings
            await self._check_budget_status()

            self.event_manager.add_event(
                EventTypes.ITERATION_COMPLETED,
                {"iteration": iteration, "total_cost": self.budget_tracker.cost},
            )

        except Exception as e:
            workflow.logger.error(f"Iteration {iteration} failed: {e}")
            self.event_manager.add_event(
                EventTypes.LLM_CALL_FAILED, {"iteration": iteration, "error": str(e)}
            )
            raise

        await self._publish_events_immediately()

    async def _execute_traditional_iteration(self) -> None:
        """Execute iteration using traditional LLM + tool approach."""
        iteration = self.state.current_iteration

        # Build system prompt with agent context and current task
        if self.state.goal:
            system_prompt = MessageBuilder.build_system_prompt(
                agent_name=self.state.agent_config.get("name", "AI Agent"),
                agent_instruction=self.state.agent_config.get(
                    "instruction", "You are a helpful AI assistant."
                ),
                goal_description=self.state.goal.description,
                success_criteria=self.state.goal.success_criteria,
                available_tools=self.state.available_tools,
            )

            # Add system message and user message if first iteration
            if iteration == 1:
                # Create messages directly using the Message class
                self.state.messages.append(Message(role="system", content=system_prompt))
                self.state.messages.append(
                    Message(role="user", content=self.state.goal.description)
                )
            # else:
            #     # Add status update for subsequent iterations (not in system prompt)
            #     # Avoid importing PromptBuilder to prevent Temporal sandbox issues
            #     status_msg = f"Iteration {iteration}/{self.state.goal.max_iterations} | Budget remaining: ${self.budget_tracker.get_remaining():.2f}"
            #     # Status updates are just regular user messages in conversation context
            #     self.state.messages.append(
            #         Message(role="user", content=f"Status: {status_msg}")
            #     )

        # Call LLM
        llm_response = await self._call_llm()

        # Process LLM response
        await self._process_llm_response(llm_response)

    async def _call_llm(self) -> dict[str, Any]:
        """Call LLM with conversation context using Pydantic models."""
        workflow.logger.info(f"Calling LLM in iteration {self.state.current_iteration}")

        # Add event for LLM call start
        self.event_manager.add_event(
            EventTypes.LLM_CALL_STARTED,
            {
                "iteration": self.state.current_iteration,
                "message_count": len(self.state.messages),
            },
        )
        await self._publish_events_immediately()

        try:
            # Convert messages to dict format for LLM call - filter out None values to match agent SDK format
            messages_dict = [
                MessageBuilder.normalize_message_dict(
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                        "name": msg.name,
                        "tool_calls": msg.tool_calls,
                    }
                )
                for msg in self.state.messages
            ]

            # Create Pydantic request model
            llm_request = LLMCallRequest(
                messages=messages_dict,
                model_id=self.state.agent_config.get("model_id"),
                tools=self.state.available_tools,
                workspace_id=self.state.user_context_data["workspace_id"],
                user_context_data=self.state.user_context_data,
                temperature=None,
                max_tokens=None,
                task_id=self.state.task_id,
                agent_id=self.state.agent_id,
                execution_id=self.state.execution_id,
            )

            response: LLMCallResult = await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[llm_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Normalize response fields to support both Pydantic model and plain dict
            if isinstance(response, dict):
                raw_usage = response.get("usage")
                cost_value = response.get("cost", 0.0)
                role_value = response.get("role", "assistant")
                content_value = response.get("content", "")
                tool_calls_value = response.get("tool_calls")
            else:
                raw_usage = getattr(response, "usage", None)
                cost_value = getattr(response, "cost", 0.0)
                role_value = getattr(response, "role", "assistant")
                content_value = getattr(response, "content", "")
                tool_calls_value = getattr(response, "tool_calls", None)

            # Extract usage info and update budget
            if raw_usage is None:
                usage_payload = {}
            else:
                # raw_usage may be a Pydantic model or a plain dict-like object
                try:
                    usage_payload = raw_usage.model_dump()  # Pydantic BaseModel
                except AttributeError:
                    try:
                        if isinstance(raw_usage, dict):
                            usage_payload = raw_usage
                        else:
                            usage_payload = dict(raw_usage.__dict__)
                    except Exception:
                        usage_payload = {}

            usage_info = {
                "cost": cost_value,
                "usage": usage_payload,
            }
            self.budget_tracker.add_cost(usage_info["cost"])

            self.event_manager.add_event(
                EventTypes.LLM_CALL_COMPLETED,
                {
                    "iteration": self.state.current_iteration,
                    "cost": usage_info["cost"],
                    "total_cost": self.budget_tracker.cost,
                    "usage": usage_info,
                    "content": content_value,
                    "tool_calls": tool_calls_value or [],
                    "role": role_value,
                },
            )
            await self._publish_events_immediately()

            # Return dict for compatibility with existing code
            return {
                "role": role_value,
                "content": content_value,
                "tool_call_id": None,  # Not provided by LLM response
                "name": None,  # Not provided by LLM response
                "tool_calls": tool_calls_value,
                "usage": usage_info,
                "cost": cost_value,
            }

        except Exception as e:
            # Simplified error handling - enriched error events are now published by the activity
            error_type = getattr(e, "type", type(e).__name__)
            error_message = str(e)

            # Generic LLM error event for workflow tracking
            self.event_manager.add_event(
                EventTypes.LLM_CALL_FAILED,
                {
                    "iteration": self.state.current_iteration,
                    "error": error_message,
                    "error_type": error_type,
                    "model_id": self.state.agent_config.get("model_id"),
                },
            )

            await self._publish_events_immediately()
            raise

    async def _process_llm_response(self, response: dict[str, Any]) -> None:
        """Process LLM response and handle tool calls."""
        # Only add non-empty messages to state
        content = response.get("content", "")
        tool_calls_raw = response.get("tool_calls")

        if content.strip() or tool_calls_raw:
            # Create Message directly from response dict
            self.state.messages.append(
                Message(
                    role=response.get("role", "assistant"),
                    content=content,
                    tool_calls=tool_calls_raw,
                )
            )
        else:
            workflow.logger.warning(
                f"Received empty LLM response in iteration {self.state.current_iteration}"
            )

        # Extract and execute tool calls - pass the response dict directly
        tool_calls = ToolCallExtractor.extract_tool_calls(response)

        if tool_calls:
            await self._execute_tool_calls(tool_calls)
        elif not content.strip():
            # If we have no content and no tool calls, this is problematic
            workflow.logger.error(
                f"LLM returned empty response with no tool calls in iteration {self.state.current_iteration}"
            )

        # Check if goal is achieved
        await self._evaluate_goal_progress()

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> None:
        """Execute MCP tools first, then handle completion signal if present."""
        completion_call = None
        for tool_call in tool_calls:
            tool_name = tool_call.function["name"]

            if tool_name == "completion":
                # Defer completion until after executing all MCP tools
                completion_call = tool_call
                continue
            else:
                # Execute MCP tool
                await self._execute_mcp_tool(tool_call)

        # After executing tools, handle completion if it was present
        if completion_call:
            await self._handle_task_completion(completion_call)

    async def _handle_task_completion(self, completion_call: ToolCall) -> None:
        """Handle task completion signal immediately."""
        # Parse completion arguments to get the result
        import json

        try:
            tool_args = json.loads(completion_call.function["arguments"])
            result_text = tool_args.get("result", "Task completed")
        except (json.JSONDecodeError, KeyError):
            result_text = "Task completed"

        # Mark task as completed immediately
        self.state.success = True
        self.state.final_response = result_text

        workflow.logger.info(f"Task completed immediately: {result_text}")
        workflow.logger.info("Workflow will terminate after this iteration")

    async def _execute_mcp_tool(self, tool_call: ToolCall) -> None:
        """Execute a single MCP tool call using Pydantic models."""
        tool_name = tool_call.function["name"]

        # Parse arguments
        import json

        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        # Approval gating before starting the tool activity
        approval_required = bool(
            self.state.goal and getattr(self.state.goal, "requires_human_approval", False)
        ) or self._tool_requires_approval(tool_name)
        if approval_required:
            # Update status and pause
            self.state.status = ExecutionStatus.WAITING_FOR_APPROVAL
            self._paused = True
            self._pause_reason = f"Awaiting approval for tool '{tool_name}'"

            # Publish approval requested event
            self.event_manager.add_event(
                EventTypes.HUMAN_APPROVAL_REQUESTED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                    "arguments": tool_args,
                    "message": "User approval required before executing tool",
                },
            )
            await self._publish_events_immediately()

            # Wait for resume signal
            await workflow.wait_condition(lambda: not self._paused)

            # Publish approval received event and update status
            self.state.status = ExecutionStatus.EXECUTING
            self.event_manager.add_event(
                EventTypes.HUMAN_APPROVAL_RECEIVED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()

        # Publish tool call started event (only after approval if required)
        self.event_manager.add_event(
            EventTypes.TOOL_CALL_STARTED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "iteration": self.state.current_iteration,
                "arguments": tool_args,
            },
        )
        await self._publish_events_immediately()

        try:
            # Create Pydantic request model for MCP tool execution
            mcp_request = MCPToolRequest(
                tool_name=tool_name,
                tool_args=tool_args,
                server_instance_id=None,
                workspace_id="system",
                tools_config=self.state.agent_config.get("tools_config"),
            )

            result_obj = await workflow.execute_activity(
                Activities.EXECUTE_MCP_TOOL,
                args=[mcp_request],
                start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

            # Normalize result to a dict for robust access
            result_dict: dict[str, Any]
            if hasattr(result_obj, "model_dump") and callable(result_obj.model_dump):
                try:
                    result_dict = result_obj.model_dump()  # type: ignore[attr-defined]
                except Exception:
                    result_dict = {}
            elif isinstance(result_obj, dict):
                result_dict = result_obj
            else:
                result_dict = getattr(result_obj, "__dict__", {}) or {}

            # Extract fields with fallbacks
            success = bool(result_dict.get("success", getattr(result_obj, "success", True)))
            # Prefer standard "result", fallback to "output", then stringify the whole object
            result_text = result_dict.get("result", getattr(result_obj, "result", None))
            if result_text is None:
                result_text = result_dict.get("output", getattr(result_obj, "output", ""))
            result_text = str(result_text) if result_text is not None else ""

            # Execution time may be named differently
            execution_time = result_dict.get(
                "execution_time", getattr(result_obj, "execution_time", None)
            ) or result_dict.get(
                "execution_time_seconds", getattr(result_obj, "execution_time_seconds", None)
            )

            # Add tool result to conversation
            self.state.messages.append(
                Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            # Publish tool completion event
            self.event_manager.add_event(
                EventTypes.TOOL_CALL_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "success": success,
                    "iteration": self.state.current_iteration,
                    "result": result_text,
                    "arguments": tool_args,
                    "execution_time": execution_time,
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(f"MCP tool '{tool_name}' executed successfully")

        except Exception as e:
            workflow.logger.error(f"MCP tool call {tool_name} failed: {e}")

            # Add error message to conversation
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Tool execution failed: {e}",
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            # Publish tool failure event
            self.event_manager.add_event(
                EventTypes.TOOL_CALL_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "error": str(e),
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()

    async def _evaluate_goal_progress(self) -> None:
        """Evaluate if the goal has been achieved."""
        try:
            # If already marked as complete by completion signal, skip evaluation
            if self.state.success:
                workflow.logger.info("Goal already marked as achieved - skipping evaluation")
                return

            # Regular goal evaluation
            # if self.state.goal:
            #     # Convert AgentGoal dataclass to dict for activity
            #     goal_dict = {
            #         "id": self.state.goal.id,
            #         "description": self.state.goal.description,
            #         "success_criteria": self.state.goal.success_criteria,
            #         "max_iterations": self.state.goal.max_iterations,
            #         "requires_human_approval": self.state.goal.requires_human_approval,
            #         "context": self.state.goal.context,
            #     }

            #     evaluation = await workflow.execute_activity(
            #         Activities.EVALUATE_GOAL_PROGRESS,
            #         args=[goal_dict, self.state.messages, self.state.current_iteration],
            #         start_to_close_timeout=ACTIVITY_TIMEOUT,
            #         retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            #     )

            #     # Update success based on evaluation
            #     self.state.success = evaluation.get("goal_achieved", False)
            #     if evaluation.get("final_response"):
            #         self.state.final_response = evaluation.get("final_response")

        except Exception as e:
            workflow.logger.warning(f"Goal evaluation failed: {e}")

    async def _check_budget_status(self) -> None:
        """Check budget status and send warnings if needed."""
        if self.budget_tracker.should_warn():
            self.event_manager.add_event(
                EventTypes.BUDGET_WARNING,
                {
                    "usage_percentage": self.budget_tracker.get_usage_percentage(),
                    "cost": self.budget_tracker.cost,
                    "limit": self.budget_tracker.budget_limit,
                    "message": self.budget_tracker.get_warning_message(),
                },
            )
            await self._publish_events_immediately()
            self.budget_tracker.mark_warning_sent()

        if self.budget_tracker.is_exceeded():
            self.event_manager.add_event(
                EventTypes.BUDGET_EXCEEDED,
                {
                    "cost": self.budget_tracker.cost,
                    "limit": self.budget_tracker.budget_limit,
                    "message": self.budget_tracker.get_exceeded_message(),
                },
            )
            await self._publish_events_immediately()

    async def _publish_events(self) -> None:
        """Publish pending events using Pydantic models."""
        events = self.event_manager.get_events()
        if not events:
            return

        try:
            events_json = [json.dumps(event) for event in events]

            # Create Pydantic request model for event publishing
            events_request = WorkflowEventsRequest(events_json=events_json)

            await workflow.execute_activity(
                Activities.PUBLISH_WORKFLOW_EVENTS,
                args=[events_request],
                start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=EVENT_PUBLISH_RETRY_ATTEMPTS),
            )

            self.event_manager.clear_events()

        except Exception as e:
            workflow.logger.warning(f"Failed to publish events: {e}")

    async def _publish_events_immediately(self) -> None:
        """Publish events immediately as they occur - fire and forget using Pydantic models."""
        pending_events = self.event_manager.get_pending_events()

        # Only proceed if we have events to publish
        if not pending_events:
            return

        # Clear pending events immediately since we're not waiting for confirmation
        self.event_manager.clear_pending_events()

        events_json = [json.dumps(event) for event in pending_events]

        # Fire and forget - publish async without waiting for result
        workflow.logger.debug(f"Publishing {len(events_json)} events immediately")

        # Create Pydantic request model for event publishing
        events_request = WorkflowEventsRequest(events_json=events_json)

        # Start the activity but don't await it (fire and forget)
        await workflow.execute_activity(
            Activities.PUBLISH_WORKFLOW_EVENTS,
            args=[events_request],
            start_to_close_timeout=EVENT_PUBLISH_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),  # Single attempt only
        )

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
        self.event_manager.add_event(
            event_type,
            {
                "success": self.state.success,
                "iterations_completed": self.state.current_iteration,
                "total_cost": self.budget_tracker.cost,
                "final_response": self.state.final_response,
            },
        )

        # Publish final events immediately
        await self._publish_events_immediately()

        # Return result - convert messages to dict format for response
        conversation_history: list[dict[str, Any]] = []
        for msg in self.state.messages:
            msg_dict: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                msg_dict["name"] = msg.name
            if msg.tool_calls:
                msg_dict["tool_calls"] = msg.tool_calls
            conversation_history.append(msg_dict)

        return AgentExecutionResult(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            success=self.state.success,
            final_response=self.state.final_response,
            total_cost=self.budget_tracker.cost if self.budget_tracker else 0.0,
            reasoning_iterations_used=self.state.current_iteration,
            conversation_history=conversation_history,
        )

    async def _handle_workflow_error(self, error: Exception) -> None:
        """Handle workflow-level errors."""
        if self.event_manager:
            self.event_manager.add_event(
                EventTypes.WORKFLOW_FAILED,
                {
                    "error": str(error),
                    "error_type": type(error).__name__,
                    "iterations_completed": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()

    def _build_goal_from_request(self, request: AgentExecutionRequest) -> AgentGoal:
        """Build goal from execution request."""
        return AgentGoal(
            id=str(request.task_id),
            description=request.task_query,
            success_criteria=request.task_parameters.get(
                "success_criteria", ["Task completed successfully"]
            ),
            max_iterations=request.task_parameters.get("max_iterations", MAX_ITERATIONS),
            requires_human_approval=request.requires_human_approval,
            context=request.task_parameters,
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
            "budget_remaining": (
                self.budget_tracker.get_remaining() if self.budget_tracker else 0.0
            ),
            "paused": self._paused,
            "pause_reason": self._pause_reason,
        }

    def _tool_requires_approval(self, tool_name: str) -> bool:
        """Check agent tools_config for per-tool user confirmation requirement."""
        try:
            tools_config = (self.state.agent_config or {}).get("tools_config") or {}
        except Exception:
            tools_config = {}

        # Check builtin tools list
        builtin_tools = tools_config.get("builtin_tools") or []
        for t in builtin_tools:
            if isinstance(t, dict):
                if t.get("tool_name") == tool_name and bool(
                    t.get("requires_user_confirmation", False)
                ):
                    return True

        # Check MCP server configs (new shape)
        mcp_server_configs = tools_config.get("mcp_server_configs") or []
        for server in mcp_server_configs:
            allowed = server.get("allowed_tools") or []
            for m in allowed:
                if (
                    isinstance(m, dict)
                    and m.get("tool_name") == tool_name
                    and bool(m.get("requires_user_confirmation", False))
                ):
                    return True

        # Check MCP servers (legacy shape)
        mcp_servers = tools_config.get("mcp_servers") or []
        for server in mcp_servers:
            allowed = server.get("allowed_tools") or []
            for m in allowed:
                if (
                    isinstance(m, dict)
                    and m.get("tool_name") == tool_name
                    and bool(m.get("requires_user_confirmation", False))
                ):
                    return True

        return False
