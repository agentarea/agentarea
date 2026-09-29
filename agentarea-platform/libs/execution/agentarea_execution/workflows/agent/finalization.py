"""Ending a run: the result, the terminal events and the persisted status."""

import json
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_common.money import ZERO, serialize_money


from ...models import AgentExecutionResult, UpdateTaskStatusRequest
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy
from .budget import BudgetMixin
from .errors import ErrorReportingMixin


class FinalizationMixin(BudgetMixin, ErrorReportingMixin):
    """Ending a run: the result, the terminal events and the persisted status."""

    async def _finalize_execution(self, result: dict[str, Any]) -> AgentExecutionResult:
        """Finalize workflow execution and return result."""
        workflow.logger.info("Finalizing workflow execution")
        execution_cancelled = self.state.status == ExecutionStatus.CANCELLED

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
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
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
                    workspace_id=self.state.workspace_id,
                    total_cost=self.budget_tracker.cost if self.budget_tracker else ZERO,
                    own_cost=self._own_cost,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )
        if self._interaction_contract_enabled:
            self._events.add_event(
                EventTypes.EXECUTION_FINISHED,
                {
                    "status": self.state.status,
                    "execution_status": "cancelled" if execution_cancelled else "completed",
                    "success": self.state.success,
                    "final_response": self.state.final_response,
                    "failure_reason": self.state.failure_reason,
                    "blocked": self.state.status == ExecutionStatus.BLOCKED,
                    "blocked_reason": self.state.blocked_reason,
                },
            )
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
            status=self.state.status,
            validation_state=self.state.validation_state,
            final_response=self.state.final_response,
            failure_reason=self.state.failure_reason,
            error_message=self.state.error_message,
            total_cost=self.budget_tracker.cost if self.budget_tracker else ZERO,
            reasoning_iterations_used=self.state.current_iteration,
            total_tool_calls=self.state.tool_calls_used,
            conversation_history=conversation_history,
        )

    async def _handle_workflow_error(self, error: Exception) -> None:
        """Handle workflow-level errors."""
        error_details = self._extract_temporal_error_details(error)
        user_message = self._get_user_facing_error(error)

        if self.event_manager:
            self.event_manager.add_event(
                EventTypes.WORKFLOW_FAILED,
                {
                    "error": user_message,
                    "error_type": self._get_user_facing_error_type(error),
                    "iterations_completed": self.state.current_iteration,
                    "status": self.state.status,
                    "blocked_reason": self.state.blocked_reason,
                },
            )
            await self._publish_events_immediately()
        workflow.logger.error(f"Workflow failed: {error_details}")

        # Update task status to failed
        if self.state and self.state.task_id:
            status = "blocked" if self.state.status == ExecutionStatus.BLOCKED else "failed"
            await workflow.execute_activity(
                Activities.UPDATE_TASK_STATUS,
                args=[
                    UpdateTaskStatusRequest(
                        user_context_data=self.state.user_context_data,
                        task_id=self.state.task_id,
                        status=status,
                        error_message=self.state.blocked_reason or error_details,
                        workspace_id=self.state.workspace_id,
                        total_cost=self.budget_tracker.cost if self.budget_tracker else None,
                        own_cost=self._own_cost if self.budget_tracker else None,
                    )
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )
