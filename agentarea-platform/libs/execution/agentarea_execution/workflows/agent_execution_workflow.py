import json
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from .context_manager import (
        ContextWindowManager,
        find_compaction_boundary,
        validate_tool_pairs,
    )
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
        ContinueAsNewState,
        Message,
        ToolCall,
    )

from ..models import (
    AgentConfigRequest,
    AgentConfigResult,
    AgentExecutionRequest,
    AgentExecutionResult,
    CompactMessagesRequest,
    CompactMessagesResult,
    LLMCallRequest,
    LLMCallResult,
    MCPToolRequest,
    RecallHistoryRequest,
    RecallHistoryResult,
    ResolveAgentToolsRequest,
    ResolveAgentToolsResult,
    ToolDiscoveryRequest,
    ToolDiscoveryResult,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
)
from .constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    DELEGATION_TIMEOUT,
    EVENT_PUBLISH_RETRY_ATTEMPTS,
    EVENT_PUBLISH_TIMEOUT,
    HEARTBEAT_TIMEOUT,
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
        self.context_manager: ContextWindowManager | None = None
        self._paused = False
        self._pause_reason = ""
        # Maps sanitized agent tool names to their config (type=agent entries)
        self._agent_tool_registry: dict[str, dict] = {}

    @workflow.signal
    async def pause_execution(self, reason: str = "Paused by user") -> None:
        """Signal to pause execution."""
        self._paused = True
        self._pause_reason = reason
        workflow.logger.info(f"Workflow paused: {reason}")

        # Add event for pause
        if self.event_manager:
            self.event_manager.add_event(
                "execution_paused",
                {
                    "reason": reason,
                    "iteration": self.state.current_iteration,
                },
            )
            # We can't await async functions in signal handlers usually,
            # but we can modify state that the workflow loop will see.
            # However, we should try to publish this event if possible or just let the loop handle it.
            # Since we are in a signal handler, we should keep it simple.

    @workflow.signal
    async def resume_execution(self, reason: str = "Resumed by user") -> None:
        """Signal to resume execution."""
        self._paused = False
        self._pause_reason = ""
        workflow.logger.info(f"Workflow resumed: {reason}")

        # Add event for resume
        if self.event_manager:
            self.event_manager.add_event(
                "execution_resumed",
                {
                    "reason": reason,
                    "iteration": self.state.current_iteration,
                },
            )

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

        # Check if this is a continue-as-new restart
        if request.continued_state:
            await self._restore_from_continued_state(request.continued_state)
            return

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

        # Store context window in state and initialize context manager
        self.state.context_window = self.state.agent_config.get("context_window", 128000)
        self.context_manager = ContextWindowManager(self.state.context_window)

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

        # Inject built-in recall_history tool for querying past execution context
        available_tools.append(
            {
                "type": "function",
                "function": {
                    "name": "recall_history",
                    "description": (
                        "Recall context from past executions of this task. "
                        "Use when you need information that may have been compacted "
                        "out of the current conversation, or to review what happened "
                        "in earlier execution attempts."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Optional search query to describe what you're looking for",
                            },
                            "event_types": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Filter by event types (e.g. ToolCallCompleted, LLMCallCompleted)",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max events to return (default 20)",
                            },
                        },
                    },
                },
            }
        )

        self.state.available_tools = available_tools

        if not StateValidator.validate_tools(self.state.available_tools):
            raise ApplicationError("Invalid tools configuration")

        # Resolve agent tools for workflow-level delegation
        await self._resolve_agent_tools()

    async def _resolve_agent_tools(self) -> None:
        """Build agent tool registry by resolving agent names to IDs.

        Identifies agent-type tools from config and resolves their IDs
        so the workflow can start child workflows directly instead of
        routing through the activity-level polling delegation.
        """
        tools_config = self.state.agent_config.get("tools", [])
        agent_names = [
            tc.get("name")
            for tc in tools_config
            if isinstance(tc, dict) and tc.get("type") == "agent" and tc.get("name")
        ]

        if not agent_names:
            return

        resolve_request = ResolveAgentToolsRequest(
            agent_names=agent_names,
            workspace_id=self.state.workspace_id,
            user_context_data=self.state.user_context_data,
        )

        result: ResolveAgentToolsResult = await workflow.execute_activity(
            Activities.RESOLVE_AGENT_TOOLS,
            args=[resolve_request],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

        # Build registry: sanitized tool name → {agent_id, agent_name, config}
        import re

        for agent_name, agent_id in result.agent_map.items():
            sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", agent_name)
            sanitized = re.sub(r"_+", "_", sanitized).strip("_")
            if not sanitized or sanitized[0].isdigit():
                sanitized = f"agent_{sanitized}"
            tool_name = f"delegate_to_{sanitized}"

            self._agent_tool_registry[tool_name] = {
                "agent_id": agent_id,
                "agent_name": agent_name,
            }

        if self._agent_tool_registry:
            workflow.logger.info(
                f"Registered {len(self._agent_tool_registry)} agent tools for delegation: "
                f"{list(self._agent_tool_registry.keys())}"
            )

    async def _restore_from_continued_state(self, continued_state: dict) -> None:
        """Restore workflow state from a continue-as-new restart."""
        workflow.logger.info("Restoring workflow from continue-as-new state")

        state = ContinueAsNewState(**continued_state)

        self.state.execution_id = state.execution_id
        self.state.agent_id = state.agent_id
        self.state.task_id = state.task_id
        self.state.user_id = state.user_id
        self.state.workspace_id = state.workspace_id
        self.state.goal = state.goal
        self.state.agent_config = state.agent_config
        self.state.available_tools = state.available_tools
        self.state.current_iteration = state.current_iteration
        self.state.budget_usd = state.budget_usd
        self.state.context_window = state.context_window
        self.state.user_context_data = state.user_context_data
        self.state.status = ExecutionStatus.EXECUTING

        # Restore messages from compacted dicts
        self.state.messages = [Message(**msg) for msg in state.messages]

        # Restore agent tool registry for delegation routing
        self._agent_tool_registry = state.agent_tool_registry

        # Initialize helpers with restored cost
        self.event_manager = EventManager(
            task_id=self.state.task_id,
            agent_id=self.state.agent_id,
            execution_id=self.state.execution_id,
        )
        self.budget_tracker = BudgetTracker(self.state.budget_usd)
        self.budget_tracker.add_cost(state.total_cost)
        self.context_manager = ContextWindowManager(self.state.context_window)

        workflow.logger.info(
            f"Restored from run {state.continued_from_run_id}, "
            f"iteration {state.current_iteration}, "
            f"cost ${state.total_cost:.4f}, "
            f"{len(self.state.messages)} messages, "
            f"{len(self._agent_tool_registry)} agent tools"
        )

    async def _continue_as_new(self) -> None:
        """Compact messages and continue workflow with fresh event history."""
        workflow.logger.info(
            f"Continue-as-new triggered at iteration {self.state.current_iteration}, "
            f"event history suggests reset"
        )

        # Compact messages before carrying state forward
        await self._compact_context_if_needed()

        # Serialize messages to dicts
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

        continued_state = ContinueAsNewState(
            execution_id=self.state.execution_id,
            agent_id=self.state.agent_id,
            task_id=self.state.task_id,
            user_id=self.state.user_id,
            workspace_id=self.state.workspace_id,
            goal=self.state.goal,
            messages=messages_dict,
            agent_config=self.state.agent_config,
            available_tools=self.state.available_tools,
            current_iteration=self.state.current_iteration,
            total_cost=self.budget_tracker.cost,
            budget_usd=self.state.budget_usd,
            context_window=self.state.context_window,
            user_context_data=self.state.user_context_data,
            continued_from_run_id=workflow.info().run_id,
            agent_tool_registry=self._agent_tool_registry,
        )

        # Publish event before continuing (persisted in DB via tier 2)
        self.event_manager.add_event(
            EventTypes.WORKFLOW_CONTINUED_AS_NEW,
            {
                "iteration": self.state.current_iteration,
                "total_cost": self.budget_tracker.cost,
                "messages_carried": len(self.state.messages),
                "continued_from_run_id": workflow.info().run_id,
                "reason": "Temporal event history size limit approaching",
            },
        )
        await self._publish_events_immediately()

        # Build new request with continued state
        new_request = AgentExecutionRequest(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            user_id=self.state.user_id,
            workspace_id=self.state.workspace_id,
            task_query=self.state.goal.description if self.state.goal else "",
            max_reasoning_iterations=self.state.goal.max_iterations
            if self.state.goal
            else MAX_ITERATIONS,
            budget_usd=self.state.budget_usd,
            continued_state=continued_state.model_dump(),
        )

        workflow.continue_as_new(args=[new_request])

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

            # Check if Temporal suggests resetting event history
            if workflow.info().is_continue_as_new_suggested():
                await self._continue_as_new()
                # continue_as_new raises an exception internally, so we won't reach here

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
            f"Checking termination conditions - success: "
            f"{self.state.success} (type: {type(self.state.success)}), "
            f"iteration: {self.state.current_iteration}"
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
            # Build instruction with skills appended
            agent_instruction = self.state.agent_config.get(
                "instruction", "You are a helpful AI assistant."
            )

            # Append skill content to instruction
            skills = self.state.agent_config.get("skills", [])
            if skills:
                skills_content = "\n\n## Skills\n"
                for skill in skills:
                    skill_name = skill.get("name", "Unnamed Skill")
                    skill_body = skill.get("content", "")
                    skill_files = skill.get("files", [])

                    skills_content += f"\n### Skill: {skill_name}\n"
                    skills_content += f"{skill_body}\n"

                    if skill_files and skill_files != ["(additional files available)"]:
                        skills_content += "\nAvailable files in this skill package:\n"
                        for f in skill_files:
                            skills_content += f"- {f}\n"

                agent_instruction = agent_instruction + skills_content

            system_prompt = MessageBuilder.build_system_prompt(
                agent_name=self.state.agent_config.get("name", "AI Agent"),
                agent_instruction=agent_instruction,
                goal_description=self.state.goal.description,
                success_criteria=self.state.goal.success_criteria,
                available_tools=self.state.available_tools,
                a2ui_enabled=self.state.agent_config.get("a2ui_enabled", False),
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

        # Check context window and compact if needed (skip first iteration)
        if self.context_manager and iteration > 1:
            messages_dict_est = [
                {"role": msg.role, "content": msg.content or ""} for msg in self.state.messages
            ]
            estimated = self.context_manager.estimate_usage(messages_dict_est)
            self.context_manager.update_usage(estimated)

            if self.context_manager.needs_compaction():
                await self._compact_context_if_needed()
            elif self.context_manager.should_warn():
                self.event_manager.add_event(
                    EventTypes.CONTEXT_WARNING,
                    {
                        "iteration": self.state.current_iteration,
                        "usage_ratio": self.context_manager.get_usage_ratio(),
                        "message_count": len(self.state.messages),
                    },
                )
                await self._publish_events_immediately()
                self.context_manager.mark_warning_sent()

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
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
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

            # Update context window manager with actual token usage
            if self.context_manager and usage_payload:
                prompt_tokens = usage_payload.get("prompt_tokens", 0)
                if prompt_tokens > 0:
                    self.context_manager.update_usage(prompt_tokens)

            # Strip A2UI JSON from the content sent to frontend via LLM_CALL_COMPLETED
            display_content = content_value
            if self.state.agent_config.get("a2ui_enabled", False) and content_value:
                from .a2ui_parser import A2UI_DELIMITER

                if A2UI_DELIMITER in content_value:
                    display_content = content_value.split(A2UI_DELIMITER, 1)[0].rstrip()

            self.event_manager.add_event(
                EventTypes.LLM_CALL_COMPLETED,
                {
                    "iteration": self.state.current_iteration,
                    "cost": usage_info["cost"],
                    "total_cost": self.budget_tracker.cost,
                    "usage": usage_info,
                    "content": display_content,
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

        # Parse and publish A2UI events if agent has A2UI enabled
        if self.state.agent_config.get("a2ui_enabled", False) and content:
            from .a2ui_parser import A2UI_DELIMITER, parse_a2ui_response

            if A2UI_DELIMITER in content:
                a2ui_result = parse_a2ui_response(content)
                if a2ui_result.a2ui_events:
                    # Replace content with text-only portion
                    content = a2ui_result.text_content
                    response["content"] = content

                    # Publish each A2UI event through the existing pipeline
                    for a2ui_event in a2ui_result.a2ui_events:
                        event_data = {k: v for k, v in a2ui_event.items() if k != "type"}
                        event_data["task_id"] = str(self.state.task_id)
                        self.event_manager.add_event(a2ui_event["type"], event_data)

                    await self._publish_events_immediately()

                if a2ui_result.parse_error:
                    workflow.logger.warning(f"A2UI parse error: {a2ui_result.parse_error}")

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
        """Execute tools, running agent delegations in parallel.

        Agent delegations are started concurrently as child workflows.
        Regular MCP/code tools run sequentially (they may have side effects
        that depend on execution order).
        """
        import asyncio

        completion_call = None
        agent_calls: list[ToolCall] = []
        regular_calls: list[ToolCall] = []

        recall_calls: list[ToolCall] = []

        for tool_call in tool_calls:
            tool_name = tool_call.function["name"]
            if tool_name == "completion":
                completion_call = tool_call
            elif tool_name == "recall_history":
                recall_calls.append(tool_call)
            elif tool_name in self._agent_tool_registry:
                agent_calls.append(tool_call)
            else:
                regular_calls.append(tool_call)

        # Run recall_history calls (can run in parallel with agent calls)
        for tool_call in recall_calls:
            await self._execute_recall_history(tool_call)

        # Run agent delegations in parallel (fan-out)
        if agent_calls:
            if len(agent_calls) == 1:
                await self._execute_agent_delegation(agent_calls[0])
            else:
                workflow.logger.info(
                    f"Fan-out: delegating to {len(agent_calls)} agents in parallel"
                )
                tasks = [self._execute_agent_delegation(tc) for tc in agent_calls]
                await asyncio.gather(*tasks)

        # Run regular tools sequentially
        for tool_call in regular_calls:
            await self._execute_mcp_tool(tool_call)

        # Handle completion last
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
            # Extract workspace_id from state (should be set from request)
            workspace_id = self.state.workspace_id or self.state.user_context_data.get(
                "workspace_id"
            )
            if not workspace_id:
                raise ValueError(
                    f"Missing workspace_id in workflow state for task {self.state.task_id}"
                )

            mcp_request = MCPToolRequest(
                tool_name=tool_name,
                tool_args=tool_args,
                server_instance_id=None,
                workspace_id=workspace_id,
                tools=self.state.agent_config.get("tools"),
            )

            result_obj = await workflow.execute_activity(
                Activities.EXECUTE_MCP_TOOL,
                args=[mcp_request],
                start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
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

    async def _execute_recall_history(self, tool_call: ToolCall) -> None:
        """Execute recall_history tool via activity to query the DB event log."""
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        request = RecallHistoryRequest(
            task_id=UUID(self.state.task_id),
            workspace_id=self.state.workspace_id,
            query=tool_args.get("query"),
            event_types=tool_args.get("event_types"),
            limit=tool_args.get("limit", 20),
            user_context_data=self.state.user_context_data,
        )

        try:
            result: RecallHistoryResult = await workflow.execute_activity(
                Activities.RECALL_HISTORY,
                args=[request],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Format events for the agent
            if result.events:
                content_parts = [result.summary, ""]
                for event in result.events:
                    content_parts.append(
                        f"[{event.get('created_at', '')}] "
                        f"{event.get('event_type', '')}: "
                        f"{json.dumps(event.get('data', {}), default=str)[:500]}"
                    )
                content = "\n".join(content_parts)
            else:
                content = "No events found for this task."

            self.state.messages.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=tool_call.id,
                    name="recall_history",
                )
            )
        except Exception as e:
            workflow.logger.error(f"Recall history failed: {e}")
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Failed to recall history: {e}",
                    tool_call_id=tool_call.id,
                    name="recall_history",
                )
            )

    async def _execute_agent_delegation(self, tool_call: ToolCall) -> None:
        """Delegate to another agent via Temporal child workflow.

        Instead of routing through execute_mcp_tool_activity (which polls),
        starts a child workflow directly and awaits its result. This is
        efficient (no polling), durable (survives worker crashes), and
        supports cancellation propagation.
        """
        tool_name = tool_call.function["name"]
        agent_info = self._agent_tool_registry[tool_name]
        agent_id = agent_info["agent_id"]
        agent_name = agent_info["agent_name"]

        # Parse the message argument
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        message = tool_args.get("message", "")

        self.event_manager.add_event(
            EventTypes.AGENT_DELEGATION_STARTED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "target_agent_id": agent_id,
                "target_agent_name": agent_name,
                "iteration": self.state.current_iteration,
                "message": message[:200],
            },
        )
        await self._publish_events_immediately()

        try:
            # Build child workflow request
            child_request = AgentExecutionRequest(
                task_id=UUID(self.state.task_id),
                agent_id=UUID(agent_id),
                user_id=self.state.user_id,
                workspace_id=self.state.workspace_id,
                task_query=message,
                max_reasoning_iterations=MAX_ITERATIONS,
                workflow_metadata={
                    "source": "agent_delegation",
                    "parent_execution_id": self.state.execution_id,
                    "parent_agent_id": self.state.agent_id,
                },
            )

            # Start child workflow and await result
            # - execution_timeout: caps total child runtime
            # - parent_close_policy: TERMINATE ensures child is cancelled
            #   if the parent workflow is cancelled or completed
            child_workflow_id = f"delegation-{self.state.execution_id}-{tool_call.id}"
            child_result: AgentExecutionResult = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                args=[child_request],
                id=child_workflow_id,
                task_queue="agent-tasks",
                execution_timeout=DELEGATION_TIMEOUT,
                parent_close_policy=ParentClosePolicy.TERMINATE,
            )

            # Extract result
            if child_result.success:
                result_text = child_result.final_response or "(Agent completed without response)"
            else:
                result_text = child_result.error_message or "(Agent failed without details)"

            self.state.messages.append(
                Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            self.event_manager.add_event(
                EventTypes.AGENT_DELEGATION_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "target_agent_name": agent_name,
                    "success": child_result.success,
                    "iteration": self.state.current_iteration,
                    "child_iterations": child_result.reasoning_iterations_used,
                    "child_cost": child_result.total_cost,
                },
            )
            await self._publish_events_immediately()

            # Account for child's cost in parent budget
            if child_result.total_cost > 0:
                self.budget_tracker.add_cost(child_result.total_cost)

            workflow.logger.info(
                f"Agent delegation to '{agent_name}' completed "
                f"(success={child_result.success}, cost=${child_result.total_cost:.4f})"
            )

        except Exception as e:
            workflow.logger.error(f"Agent delegation to '{agent_name}' failed: {e}")

            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Agent delegation failed: {e}",
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )

            self.event_manager.add_event(
                EventTypes.AGENT_DELEGATION_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "target_agent_name": agent_name,
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

    async def _compact_context_if_needed(self) -> bool:
        """Check context usage and compact if threshold exceeded.

        Uses the head-and-tail strategy:
        1. Keep system prompt (head)
        2. Summarize middle messages via LLM
        3. Keep recent messages (tail)
        4. Validate tool pairs aren't broken

        Returns True if compaction was performed.
        """
        if not self.context_manager or not self.context_manager.needs_compaction():
            return False

        workflow.logger.info(
            f"Context compaction triggered at {self.context_manager.get_usage_ratio():.1%} usage"
        )

        # Convert messages to dict for boundary finding
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

        # Find safe compaction boundary
        boundary = find_compaction_boundary(messages_dict)
        if boundary <= 1:
            workflow.logger.warning("No safe compaction boundary found, skipping")
            return False

        # Messages to compact: everything between system prompt and boundary
        messages_to_compact = messages_dict[1:boundary]
        if not messages_to_compact:
            return False

        # Call compaction activity
        try:
            compact_request = CompactMessagesRequest(
                messages_to_compact=messages_to_compact,
                model_id=self.state.agent_config.get("model_id"),
                workspace_id=self.state.workspace_id,
                user_context_data=self.state.user_context_data,
            )

            result: CompactMessagesResult = await workflow.execute_activity(
                Activities.COMPACT_MESSAGES,
                args=[compact_request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            # Rebuild message list: system prompt + summary + kept recent messages
            system_msg = self.state.messages[0]
            recent_messages = list(self.state.messages[boundary:])

            summary_msg = Message(
                role="user",
                content=f"[Previous conversation summary]\n{result.summary}",
            )

            self.state.messages = [system_msg, summary_msg, *recent_messages]

            # Validate tool pairs in new message list
            new_messages_dict = [
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
            if not validate_tool_pairs(new_messages_dict):
                workflow.logger.error("Tool pair validation failed after compaction!")
                # Repair: drop orphaned tool results
                tool_use_ids: set[str] = set()
                for msg in self.state.messages:
                    if msg.role == "assistant" and msg.tool_calls:
                        for tc in msg.tool_calls:
                            if isinstance(tc, dict) and tc.get("id"):
                                tool_use_ids.add(tc["id"])
                self.state.messages = [
                    msg
                    for msg in self.state.messages
                    if not (msg.role == "tool" and msg.tool_call_id not in tool_use_ids)
                ]

            self.context_manager.mark_compacted()

            # Publish compaction event
            self.event_manager.add_event(
                EventTypes.CONTEXT_COMPACTED,
                {
                    "iteration": self.state.current_iteration,
                    "messages_compacted": result.original_message_count,
                    "tokens_saved": result.estimated_tokens_saved,
                    "compaction_number": self.context_manager.compaction_count,
                    "messages_remaining": len(self.state.messages),
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(
                f"Compacted {result.original_message_count} messages, "
                f"~{result.estimated_tokens_saved} tokens saved, "
                f"{len(self.state.messages)} messages remaining"
            )
            return True

        except Exception as e:
            workflow.logger.error(f"Context compaction failed: {e}")
            return False

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
            events_request = WorkflowEventsRequest(
                events_json=events_json,
                workspace_id=self.state.workspace_id,
                user_id=self.state.user_id,
            )

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
        events_request = WorkflowEventsRequest(
            events_json=events_json,
            workspace_id=self.state.workspace_id,
            user_id=self.state.user_id,
        )

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

        # Update task status in the database
        final_status = "completed" if self.state.success else "failed"
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    task_id=self.state.task_id,
                    status=final_status,
                    result=self.state.final_response,
                    workspace_id=self.state.workspace_id,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
        )

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

        # Update task status to failed
        if self.state and self.state.task_id:
            await workflow.execute_activity(
                Activities.UPDATE_TASK_STATUS,
                args=[
                    UpdateTaskStatusRequest(
                        task_id=self.state.task_id,
                        status="failed",
                        error_message=str(error),
                        workspace_id=self.state.workspace_id,
                    )
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=DEFAULT_RETRY_ATTEMPTS),
            )

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
            "context": self.context_manager.get_status() if self.context_manager else None,
        }

    def _tool_requires_approval(self, tool_name: str) -> bool:
        """Check agent tools for per-tool user confirmation requirement."""
        try:
            tools = (self.state.agent_config or {}).get("tools") or []
        except Exception:
            tools = []

        # Check each tool in the list
        for tool_config in tools:
            if not isinstance(tool_config, dict):
                continue

            # Check if this is the tool we're looking for
            if tool_config.get("name") != tool_name:
                continue

            # Check settings for requires_user_confirmation
            settings = tool_config.get("settings", {})
            if isinstance(settings, dict) and bool(
                settings.get("requires_user_confirmation", False)
            ):
                return True

        return False
