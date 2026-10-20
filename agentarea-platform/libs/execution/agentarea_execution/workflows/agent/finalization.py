"""Ending a run: the result, the terminal events and the persisted status."""

import json
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_common.money import ZERO, serialize_money


from ...models import AgentExecutionResult, ConversationResumeSnapshot, UpdateTaskStatusRequest
from ..constants import (
    EventTypes,
    ExecutionStatus,
)
from .budget import BudgetMixin
from .errors import ErrorReportingMixin
from .patches import CONVERSATION_RESUME_SNAPSHOT_PATCH, RESUME_AFTER_STOP_OR_FAILURE_PATCH


class FinalizationMixin(BudgetMixin, ErrorReportingMixin):
    """Ending a run: the result, the terminal events and the persisted status."""

    async def _finalize_execution(self, result: dict[str, Any]) -> AgentExecutionResult:
        """Finalize workflow execution and return result."""
        workflow.logger.info("Finalizing workflow execution")
        execution_cancelled = self.state.status == ExecutionStatus.CANCELLED
        # A stop that interrupted a tool or model call is final now, but the run
        # stays open to record what that call did; the live feed stays open too.
        settling = execution_cancelled and self._has_stopped_work()

        # Determine final status.
        # If task_complete was already called, the task succeeded regardless of
        # follow-up message processing failures.
        if (self._completion_event_published or self.state.success) and (
            self.state.final_response and self.state.final_response.strip()
        ):
            self.state.status = ExecutionStatus.COMPLETED
            self.state.success = True
        else:
            if self._completion_event_published or self.state.success:
                self.state.failure_reason = "missing_final_response"
                self.state.error_message = "Task ended without a final response"
            elif self.state.status == ExecutionStatus.BLOCKED:
                self.state.failure_reason = self.state.failure_reason or "blocked"
                self.state.error_message = self.state.error_message or self.state.blocked_reason
            elif not self.state.failure_reason:
                self.state.failure_reason = "task_unsuccessful"
                self.state.error_message = self.state.error_message or "Task did not complete"
            self.state.success = False
            if self.state.status not in {ExecutionStatus.BLOCKED, ExecutionStatus.CANCELLED}:
                self.state.status = ExecutionStatus.FAILED

        # Only publish completion/failure event if not already published at task_complete
        if not self._completion_event_published:
            event_type = (
                EventTypes.WORKFLOW_CANCELLED
                if self.state.status == ExecutionStatus.CANCELLED
                else EventTypes.WORKFLOW_COMPLETED
                if self.state.success
                else EventTypes.WORKFLOW_FAILED
            )
            self._events.add_event(
                event_type,
                {
                    "success": self.state.success,
                    "iterations_completed": self.state.current_iteration,
                    "total_cost": serialize_money(self._budget.cost),
                    "tokens_used": self.state.tokens_used,
                    "final_response": self.state.final_response,
                    "status": self.state.status,
                    "failure_reason": self.state.failure_reason,
                    "error": self.state.error_message,
                    "blocked_reason": self.state.blocked_reason,
                    **(
                        {"blocked": self.state.status == ExecutionStatus.BLOCKED}
                        if self._interaction_contract_enabled
                        else {}
                    ),
                    **({"execution_status": "settling"} if settling else {}),
                    "validation_state": self.state.validation_state,
                },
            )
            await self._publish_events_immediately()

        # Update task status in the database.
        # If task_complete already set status to "completed", don't downgrade it.
        if self.state.success:
            final_status = "completed"
        elif self.state.status == ExecutionStatus.BLOCKED:
            final_status = "blocked"
        elif self.state.status == ExecutionStatus.CANCELLED:
            final_status = "cancelled"
        else:
            final_status = "failed"
        self._keep_queued_messages()
        conversation_pending = self._conversation_payload()
        # A completed, stopped or failed conversation can be continued by a later
        # message, or a retry, after the workflow closes; the snapshot tells that
        # run where the log stands.
        conversation_resume = (
            self._conversation_resume_snapshot(len(conversation_pending))
            if (
                final_status == "completed"
                or (
                    final_status in ("cancelled", "failed")
                    and workflow.patched(RESUME_AFTER_STOP_OR_FAILURE_PATCH)
                )
            )
            and not self._is_delegation_child()
            and workflow.patched(CONVERSATION_RESUME_SNAPSHOT_PATCH)
            and self._conversation_resumable_from_here()
            else None
        )
        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status=final_status,
                result=json.dumps(
                    {
                        "response": self.state.final_response,
                        "validation_state": self.state.validation_state,
                    }
                )
                if self.state.final_response
                else None,
                error_message=self.state.error_message
                or (self.state.blocked_reason if final_status == "blocked" else None),
                failure_reason=None if self.state.success else self.state.failure_reason,
                workspace_id=self.state.workspace_id,
                total_cost=self.budget_tracker.cost if self.budget_tracker else ZERO,
                own_cost=self._own_cost,
                tokens_used=self.state.tokens_used,
                conversation=self._conversation_window(),
                conversation_pending=conversation_pending,
                conversation_resume=conversation_resume,
            )
        )
        self._mark_conversation_written()
        if self._interaction_contract_enabled and not settling:
            self._add_execution_finished_event(execution_cancelled)
            await self._publish_events_immediately()

        return AgentExecutionResult(
            task_id=UUID(self.state.task_id),
            agent_id=UUID(self.state.agent_id),
            success=self.state.success,
            status=self.state.status,
            validation_state=self.state.validation_state,
            final_response=self.state.final_response,
            failure_reason=self.state.failure_reason,
            error_message=self.state.error_message,
            total_cost=self.budget_tracker.cost if self.budget_tracker else ZERO,
            reasoning_iterations_used=self.state.current_iteration,
            total_tool_calls=self.state.tool_calls_used,
        )

    def _conversation_resume_snapshot(self, pending_count: int) -> ConversationResumeSnapshot:
        """The window and counters as they stand once the pending entries are written."""
        return ConversationResumeSnapshot(
            head_seqs=list(self.state.context_head_seqs),
            tail_start=self.state.context_tail_start,
            next_seq=self.state.conversation_next_seq + pending_count,
            current_iteration=max(self.state.current_iteration, 1),
            tool_calls_used=self.state.tool_calls_used,
            tokens_used=self.state.tokens_used,
            last_prompt_tokens=self.state.last_prompt_tokens,
        )

    async def _handle_workflow_error(self, error: Exception) -> None:
        """Handle workflow-level errors."""
        error_details = self._extract_temporal_error_details(error)
        user_message = self._get_user_facing_error(error)
        blocked = self.state.status == ExecutionStatus.BLOCKED

        if self.event_manager:
            self.event_manager.add_event(
                EventTypes.WORKFLOW_FAILED,
                {
                    "error": user_message,
                    "error_type": self._get_user_facing_error_type(error),
                    "failure_reason": self._failure_cause(error),
                    "error_detail": self._error_detail(error),
                    **({"blocked": True, "retryable": False} if blocked else {}),
                    "iterations_completed": self.state.current_iteration,
                    "total_cost": serialize_money(
                        self.budget_tracker.cost if self.budget_tracker else ZERO
                    ),
                    "tokens_used": self.state.tokens_used,
                    "status": self.state.status,
                    "blocked_reason": self.state.blocked_reason,
                },
            )
            await self._publish_events_immediately()
        workflow.logger.error(f"Workflow failed: {error_details}")

        # Update task status to failed
        if self.state and self.state.task_id:
            status = "blocked" if blocked else "failed"
            conversation_resume = None
            if (
                status == "failed"
                and not self._is_delegation_child()
                and workflow.patched(RESUME_AFTER_STOP_OR_FAILURE_PATCH)
            ):
                self._answer_unanswered_tool_calls(
                    "Not executed: the run failed before this call ran."
                )
                self._keep_queued_messages()
                if self._conversation_resumable_from_here():
                    conversation_resume = self._conversation_resume_snapshot(
                        len(self.state.messages)
                    )
            else:
                self._keep_queued_messages()
            await self._persist_task_status(
                UpdateTaskStatusRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    status=status,
                    error_message=self.state.blocked_reason or error_details,
                    failure_reason=self._failure_cause(error) or self.state.failure_reason,
                    workspace_id=self.state.workspace_id,
                    total_cost=self.budget_tracker.cost if self.budget_tracker else None,
                    own_cost=self._own_cost if self.budget_tracker else None,
                    tokens_used=self.state.tokens_used,
                    conversation=self._conversation_window(),
                    conversation_pending=self._conversation_payload(),
                    conversation_resume=conversation_resume,
                )
            )
            self._mark_conversation_written()
