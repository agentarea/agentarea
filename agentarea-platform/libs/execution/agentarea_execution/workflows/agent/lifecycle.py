"""The main loop: iterating, stopping, waiting for continuation and follow-ups."""

from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from agentarea_common.money import serialize_money, to_money

    from ..models import Message


from ...models import UpdateTaskStatusRequest
from ..constants import (
    CONTINUATION_TIMEOUT,
    EventTypes,
    ExecutionStatus,
)
from .budget import LLM_RUN_CAP_FAILURE_REASON, MONTHLY_CAP_FAILURE_REASON
from .continue_as_new import ContinueAsNewMixin
from .limits import run_limit_reason
from .llm_turn import LLMTurnMixin
from .patches import CONTINUATION_WITHIN_POLICY_CEILING_PATCH, LONG_RUN_LOOP_PATCH
from .stopping import STOPPED_BEFORE_RUNNING, STOPPED_WHILE_RUNNING


class LifecycleMixin(LLMTurnMixin, ContinueAsNewMixin):
    """The main loop: iterating, stopping, waiting for continuation and follow-ups."""

    async def _execute_main_loop(self) -> dict[str, Any]:
        """Main execution loop with dynamic termination conditions.

        After the agent calls task_complete, the workflow enters awaiting_input
        state instead of terminating. It waits for follow-up user messages
        (via queue_message signal) or times out after AWAIT_INPUT_TIMEOUT.
        """
        workflow.logger.info("Starting main execution loop")

        self.state.status = ExecutionStatus.EXECUTING
        await self._check_monthly_spend_cap()
        loop_checks = workflow.patched(LONG_RUN_LOOP_PATCH)

        while True:
            # Every path back to the top — a follow-up turn, a granted
            # continuation, a resume — honours a pause and rolls the history
            # over when Temporal asks, not only the plain next-iteration path.
            if loop_checks:
                if self._paused:
                    await workflow.wait_condition(lambda: not self._paused)
                    await self._check_monthly_spend_cap()
                if workflow.info().is_continue_as_new_suggested():
                    await self._continue_as_new()

            # Increment iteration count
            self.state.current_iteration += 1

            # Check if we should continue before starting the iteration
            should_continue, failure_reason, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(
                    f"Stopping execution before iteration {self.state.current_iteration}: {reason}"
                )
                # Decrement since we didn't actually execute this iteration
                self.state.current_iteration -= 1
                if failure_reason and await self._await_continuation(failure_reason, reason):
                    await self._check_monthly_spend_cap()
                    continue
                self._record_unsuccessful_termination(
                    failure_reason, self._termination_message(failure_reason, reason)
                )
                break

            workflow.logger.info(f"Starting iteration {self.state.current_iteration}")

            # Execute iteration
            try:
                await self._execute_iteration()
            except ApplicationError as error:
                failure_reason = run_limit_reason(error)
                if failure_reason is None:
                    raise
                self._answer_unanswered_tool_calls(
                    "Not executed: the run stopped at a resource limit before this call ran."
                )
                reason = self._run_limit_message(failure_reason)
                if await self._await_continuation(failure_reason, reason):
                    await self._check_monthly_spend_cap()
                    continue
                self._record_unsuccessful_termination(
                    failure_reason, self._termination_message(failure_reason, reason)
                )
                break

            if self.state.validation_terminal:
                break
            if self._interaction_contract_enabled and self.state.status == ExecutionStatus.BLOCKED:
                break

            # If agent completed the task, wait for follow-up messages.
            # Exception: a workflow spawned via agent delegation has no
            # end-user owning its conversation — its parent is awaiting the
            # result via execute_child_workflow. Sitting in await_input
            # would block the parent until DELEGATION_TIMEOUT cancels us.
            # Future "mode=conversation" delegations would opt in here.
            if self._awaiting_input:
                if self._is_delegation_child():
                    workflow.logger.info("Delegated child completed — exiting without await_input")
                    break
                await self._await_follow_up()
                # If we got a new message, continue the loop
                if not self._awaiting_input:
                    self._reset_for_follow_up()
                    await self._check_monthly_spend_cap()
                    continue
                # Timed out — exit the loop
                break

            # Check if we should finish after completing the iteration
            should_continue, failure_reason, reason = self._should_continue_execution()
            if not should_continue:
                workflow.logger.info(
                    f"Stopping execution after iteration {self.state.current_iteration}: {reason}"
                )
                if failure_reason and await self._await_continuation(failure_reason, reason):
                    await self._check_monthly_spend_cap()
                    continue
                self._record_unsuccessful_termination(
                    failure_reason, self._termination_message(failure_reason, reason)
                )
                break

            # Check if Temporal suggests resetting event history
            if workflow.info().is_continue_as_new_suggested():
                await self._continue_as_new()
                # continue_as_new raises an exception internally, so we won't reach here

            # Check for pause
            if self._paused:
                await workflow.wait_condition(lambda: not self._paused)
                await self._check_monthly_spend_cap()

        return {"iterations_completed": self.state.current_iteration}

    async def _await_continuation(self, failure_reason: str, message: str) -> bool:
        """Idle durably until the user grants resources or the window expires."""
        if failure_reason in (MONTHLY_CAP_FAILURE_REASON, LLM_RUN_CAP_FAILURE_REASON):
            return False
        if workflow.patched(
            CONTINUATION_WITHIN_POLICY_CEILING_PATCH
        ) and self._limit_at_policy_ceiling(failure_reason):
            self._policy_fixed_limit = failure_reason
            return False
        if (
            self._interaction_contract_enabled
            and self.state.interaction_capabilities.channel == "none"
        ):
            return False
        if self._is_delegation_child():
            return False

        self._record_unsuccessful_termination(failure_reason, message)
        self._waiting_for_continuation = True
        self._continuation_failure_reason = failure_reason
        self._continuation_message = message
        self.state.status = ExecutionStatus.WAITING_FOR_CONTINUATION

        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status=ExecutionStatus.WAITING_FOR_CONTINUATION,
                error_message=message,
                failure_reason=failure_reason,
                workspace_id=self.state.workspace_id,
            )
        )
        self._events.add_event(
            EventTypes.WORKFLOW_AWAITING_CONTINUATION,
            {
                "failure_reason": failure_reason,
                "message": message,
                "iterations_used": self.state.current_iteration,
                "max_iterations": self.state.goal.max_iterations if self.state.goal else None,
                "cost": serialize_money(self._budget.cost),
                "budget_usd": serialize_money(self._budget.budget_limit),
                "tokens_used": self.state.tokens_used,
                "max_tokens": self._policy_limit("tokens", "max_tokens"),
                "tool_calls_used": self.state.tool_calls_used,
                "max_tool_calls_total": self._policy_limit("execution", "max_tool_calls_total"),
                "continuation_timeout_seconds": int(CONTINUATION_TIMEOUT.total_seconds()),
            },
        )
        await self._publish_events_immediately()

        try:
            await workflow.wait_condition(
                lambda: not self._waiting_for_continuation,
                timeout=CONTINUATION_TIMEOUT,
            )
        except TimeoutError:
            self._waiting_for_continuation = False
            self.state.status = ExecutionStatus.FAILED
            workflow.logger.info("Continuation window expired: %s", failure_reason)
            return False

        original_reason = self._continuation_failure_reason
        self._events.add_event(
            EventTypes.WORKFLOW_CONTINUED,
            {
                "previous_failure_reason": original_reason,
                "continuation_count": self._continuation_count,
                "max_iterations": self.state.goal.max_iterations if self.state.goal else None,
                "budget_usd": serialize_money(self._budget.budget_limit),
            },
        )
        await self._publish_events_immediately()
        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status="running",
                workspace_id=self.state.workspace_id,
            )
        )
        self._continuation_failure_reason = None
        self._continuation_message = None
        return True

    async def _await_follow_up(self) -> None:
        """Wait for a follow-up user message or timeout.

        The workflow idles here consuming zero worker resources. Temporal
        persists the state and wakes the workflow on signal or timeout.
        Uses try/except per Temporal SDK docs (TimeoutError on timeout).
        """
        window = self._follow_up_window()
        if window is None:
            return
        workflow.logger.info(
            f"Task completed — waiting for follow-up messages ({int(window.total_seconds())}s)"
        )

        try:
            await workflow.wait_condition(
                lambda: (
                    bool(self._message_queue)
                    or (self._interaction_contract_enabled and bool(self._a2ui_action_queue))
                ),
                timeout=window,
            )
        except TimeoutError:
            workflow.logger.info("Await timeout reached, finalizing workflow")
            return

        workflow.logger.info("Follow-up message received, resuming execution")
        self._awaiting_input = False

        # Update task status back to running
        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status="running",
                workspace_id=self.state.workspace_id,
            )
        )

    def _should_continue_execution(self) -> tuple[bool, str | None, str]:
        """Comprehensive check for whether execution should continue.

        Checks all termination conditions:
        - Goal achievement
        - Maximum iterations reached
        - Budget exceeded
        - Workflow cancelled/paused state

        Returns:
            tuple[bool, str | None, str]:
                (should_continue, failure_reason, human_message)
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
            return False, None, "Goal achieved successfully"

        if self._monthly_cap_message:
            return False, MONTHLY_CAP_FAILURE_REASON, self._monthly_cap_message

        llm_cap_message = self._llm_run_cap_message()
        if llm_cap_message:
            return False, LLM_RUN_CAP_FAILURE_REASON, llm_cap_message

        # Check maximum iterations
        if self.state.goal is None:
            raise ApplicationError(
                "workflow goal is missing from execution state",
                type="InvalidExecutionSnapshot",
                non_retryable=True,
            )
        max_iterations = self.state.goal.max_iterations
        if self.state.current_iteration > max_iterations:
            workflow.logger.info(
                f"Max iterations reached ({max_iterations}) - terminating workflow"
            )
            return (
                False,
                "iteration_limit",
                f"Maximum iterations reached ({max_iterations})",
            )

        # Check budget constraints
        if self.budget_tracker and self.budget_tracker.is_exceeded():
            workflow.logger.info("Budget exceeded - terminating workflow")
            return (
                False,
                "budget_exceeded",
                f"Budget exceeded ({self.budget_tracker.describe(self.budget_tracker.cost)}/"
                f"{self.budget_tracker.describe(self.budget_tracker.budget_limit)})",
            )

        # Check for cancellation (this could be extended for other cancellation conditions)
        # For now, we don't have explicit cancellation, but this is where it would go

        # If we get here, execution should continue
        return True, None, "Continue execution"

    def _policy_limit(self, section: str, key: str) -> int | None:
        return ((self.state.effective_policy or {}).get(section) or {}).get(key)

    def _limit_at_policy_ceiling(self, failure_reason: str) -> bool:
        """Whether the limit the run hit is already what a workspace, agent or user policy allows.

        A continuation grant cannot raise it then, so the run does not wait for one.
        The ceilings are those the task was created under, in its governance snapshot.
        """
        snapshot = (self._workflow_metadata or {}).get("governance_snapshot") or {}
        ceiling = (snapshot.get("limit_ceilings") or {}).get(failure_reason)
        if ceiling is None:
            return False
        current: Any = {
            "iteration_limit": self.state.goal.max_iterations if self.state.goal else None,
            "tool_call_limit": self._policy_limit("execution", "max_tool_calls_total"),
            "token_limit": self._policy_limit("tokens", "max_tokens"),
            "budget_exceeded": self._budget.budget_limit,
        }.get(failure_reason)
        return current is not None and to_money(current) >= to_money(ceiling)

    def _termination_message(self, failure_reason: str | None, message: str) -> str:
        """Why the run stopped, saying so when a policy fixes the limit it hit."""
        if failure_reason is None or failure_reason != self._policy_fixed_limit:
            return message
        return (
            f"{message}. A workspace, agent or user policy sets this limit, so it cannot be raised"
        )

    def _run_limit_message(self, failure_reason: str) -> str:
        """The user-facing explanation of why the run stopped at a limit."""
        if failure_reason == "token_limit":
            limit = self._policy_limit("tokens", "max_tokens")
            return f"Token budget exhausted ({self.state.tokens_used}/{limit} tokens)"
        if failure_reason == "tool_call_limit":
            limit = self._policy_limit("execution", "max_tool_calls_total")
            return f"Tool-call budget exhausted ({self.state.tool_calls_used}/{limit} calls)"
        return (
            f"Budget exceeded ({self._budget.describe(self._budget.cost)}/"
            f"{self._budget.describe(self._budget.budget_limit)})"
        )

    def _answer_stopped_tool_calls(self) -> None:
        """Answer the calls a stop interrupted, then the ones it kept from running.

        The stopped run's log stays a conversation a model accepts, so a later
        message continues it.
        """
        stopped = {call.tool_call.id for call in self._stopped_tool_calls}
        calls, _answered = self._last_turn_tool_calls()
        for tool_call in calls:
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if call_id in stopped:
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=STOPPED_WHILE_RUNNING,
                        tool_call_id=call_id,
                        name=(tool_call.get("function") or {}).get("name"),
                    )
                )
        self._answer_unanswered_tool_calls(STOPPED_BEFORE_RUNNING)

    def _record_unsuccessful_termination(self, failure_reason: str | None, message: str) -> None:
        """Persist a stable failure code and a user-facing explanation."""
        if self.state.success or failure_reason is None:
            return

        self.state.failure_reason = failure_reason
        self.state.error_message = message

    def _reset_for_follow_up(self) -> None:
        """Start a new turn without carrying terminal success from the prior turn."""
        self._completion_event_published = False
        self.state.success = False
        self.state.status = ExecutionStatus.EXECUTING
        self.state.final_response = ""
        self.state.failure_reason = None
        self.state.error_message = None
        self.state.blocked_reason = None
        self.state.validation_state = "pending"
        self.state.validation_repair_attempts = 0
        self.state.validation_terminal = False
