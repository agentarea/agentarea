import asyncio
from collections.abc import Callable
from typing import Any, cast

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    # The sandboxed ``..models`` and ``.retry`` build on these, which are not
    # sandbox-safe; they must be passed through before either is imported.
    import agentarea_agents_sdk.tools.mcp_tool_identity  # noqa: F401  # pyright: ignore[reportUnusedImport]
    import agentarea_governance.domain.exceptions  # noqa: F401  # pyright: ignore[reportUnusedImport]
    from agentarea_common.auth.tool_authorization import caller_can_approve
    from agentarea_common.money import serialize_money
    from pydantic import ValidationError

    from .helpers import EventManager

from ..models import (
    AgentExecutionRequest,
    AgentExecutionResult,
    UpdateTaskGovernanceSnapshotRequest,
    UpdateTaskGovernanceSnapshotResult,
)
from .agent.commands import CommandsMixin
from .agent.finalization import FinalizationMixin
from .agent.initialization import InitializationMixin
from .agent.lifecycle import LifecycleMixin
from .agent.patches import APPROVAL_RESPONSE_ONCE_PATCH
from .constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from .retry import make_retry_policy


@workflow.defn
class AgentExecutionWorkflow(CommandsMixin, InitializationMixin, LifecycleMixin, FinalizationMixin):
    """Agent execution workflow without ADK dependency."""

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

    _MAX_A2UI_QUEUE_SIZE = 50

    @workflow.signal
    async def handle_a2ui_action(self, action_data: dict[str, Any]) -> None:
        """Signal from frontend when user interacts with an A2UI surface.

        The action is queued and injected as a user message on the next LLM call,
        so the agent can respond to the user's interaction.
        """
        if self._interaction_contract_enabled:
            surface_id = action_data.get("surface_id")
            actions = (
                self.state.a2ui_surfaces.get(surface_id, {}) if isinstance(surface_id, str) else {}
            )
            name = action_data.get("name")
            component_id = action_data.get("source_component_id")
            if (
                not self._a2ui_available
                or name not in actions.values()
                or (component_id and actions.get(component_id) != name)
            ):
                workflow.logger.warning("Ignoring unavailable or undeclared A2UI action")
                return
            if self._pending_input_requests:
                for request_id, pending in self._pending_input_requests.items():
                    if pending.get("surface_id") == surface_id and not pending.get("resolved"):
                        # Secrets can only enter via the authenticated input endpoint.
                        if any(q.get("type") == "secret" for q in pending["questions"]):
                            return
                        context = action_data.get("context")
                        if isinstance(context, dict):
                            answers = dict(context)
                            # ChoicePicker uses string lists even in single-selection mode.
                            for question in pending["questions"]:
                                value = answers.get(question["id"])
                                if (
                                    question.get("type") == "select"
                                    and isinstance(value, list)
                                    and len(value) == 1
                                    and isinstance(value[0], str)
                                ):
                                    answers[question["id"]] = value[0]
                            self._handle_submit_user_input(
                                {"input_request_id": request_id, "answers": answers}
                            )
                        return
                # An unrelated action is not an answer and must not become one later.
                return
        if len(self._a2ui_action_queue) >= self._MAX_A2UI_QUEUE_SIZE:
            workflow.logger.warning("A2UI action queue full, dropping oldest")
            self._a2ui_action_queue.pop(0)
        self._a2ui_action_queue.append(action_data)
        workflow.logger.info(
            f"A2UI action received: {action_data.get('name', 'unknown')} "
            + f"on surface {action_data.get('surface_id', 'unknown')}"
        )

    @workflow.signal
    async def resolve_escalation(
        self, escalation_id: str, approved: bool, comment: str = "", resolved_by: str = ""
    ) -> None:
        """Signal to approve or deny a specific tool escalation.

        Authoritative authorization point: only a designated approver (per the
        task's ApprovalPolicy) may resolve. Unauthorized signals are ignored so
        the API/activity boundary cannot bypass policy.
        """
        if escalation_id in self._pending_escalations:
            esc = self._pending_escalations[escalation_id]

            if not caller_can_approve(esc.approvers, resolved_by):
                workflow.logger.warning(
                    f"Unauthorized escalation resolution for {escalation_id} by "
                    f"'{resolved_by or 'unknown'}'; approvers={esc.approvers}. Ignored."
                )
                return

            esc.resolved = True
            esc.approved = approved
            esc.approved_by = resolved_by or None
            esc.comment = comment or None
            esc.deny_comment = comment if not approved else None

            # The waiting approval flow emits the one approval.response.
            if not workflow.patched(APPROVAL_RESPONSE_ONCE_PATCH):
                event_type = (
                    EventTypes.HUMAN_APPROVAL_RECEIVED
                    if approved
                    else EventTypes.HUMAN_APPROVAL_DENIED
                )
                cast(EventManager, self.event_manager).add_event(
                    event_type,
                    {
                        "escalation_id": escalation_id,
                        "tool_name": esc.tool_name,
                        "tool_call_id": esc.tool_call_id,
                        "approved": approved,
                        "comment": comment,
                        "approved_by": resolved_by or None,
                        "iteration": self.state.current_iteration,
                    },
                )
            workflow.logger.info(
                f"Escalation {escalation_id} resolved by '{resolved_by or 'unknown'}': "
                + f"approved={approved}"
                + (f" comment='{comment}'" if comment else "")
            )

    @workflow.signal
    async def workflow_command(self, command: str, payload: dict[str, Any]) -> None:
        """Generic command signal for mid-execution control."""
        handlers: dict[str, Callable[[dict[str, Any]], None]] = {
            "change_model": self._handle_change_model,
            "update_budget": self._handle_update_budget,
            "continue_execution": self._handle_continue_execution,
            "queue_message": self._handle_queue_message,
            "submit_user_input": self._handle_submit_user_input,
            "remove_message": self._handle_remove_message,
        }
        handler = handlers.get(command)
        if handler:
            # An exception escaping a signal handler fails every workflow task retry.
            try:
                handler(payload)
            except (ValueError, KeyError) as error:
                reason = (
                    "; ".join(
                        f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                        for e in error.errors(include_url=False)
                    )
                    if isinstance(error, ValidationError)
                    else str(error)
                )
                workflow.logger.warning(
                    f"Rejected malformed workflow command {command!r}: {reason}", exc_info=True
                )
                if self.event_manager:
                    self.event_manager.add_event(
                        EventTypes.WORKFLOW_COMMAND_REJECTED,
                        {
                            "command": command,
                            "reason": reason,
                            "iteration": self.state.current_iteration,
                        },
                    )
                return
            if self.event_manager:
                self.event_manager.add_event(
                    EventTypes.WORKFLOW_COMMAND_RECEIVED,
                    {
                        "command": command,
                        "iteration": self.state.current_iteration,
                    },
                )
        else:
            workflow.logger.warning(f"Unknown workflow command: {command}")

    @workflow.update
    async def continue_execution(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist and atomically apply a re-resolved policy revision."""
        info, rejection = self._prepare_continuation(payload)
        if rejection is not None:
            return rejection
        if info is None or info.governance_snapshot is None:
            raise RuntimeError("continuation validation returned no result")

        result: UpdateTaskGovernanceSnapshotResult = await workflow.execute_activity(
            Activities.UPDATE_TASK_GOVERNANCE_SNAPSHOT,
            args=[
                UpdateTaskGovernanceSnapshotRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    workspace_id=self.state.workspace_id,
                    governance_snapshot=info.governance_snapshot,
                )
            ],
            result_type=UpdateTaskGovernanceSnapshotResult,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )
        if not result.success:
            raise ApplicationError(
                result.error or "Failed to persist governance snapshot",
                type="GovernanceSnapshotPersistenceFailed",
                non_retryable=True,
            )
        return self._commit_continuation(info)

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

        except asyncio.CancelledError:
            if self._interaction_contract_enabled:
                self._pending_input_requests.clear()
                self._awaiting_input = False
                self.state.status = ExecutionStatus.CANCELLED
                if not self.state.success:
                    self.state.failure_reason = "cancelled"
                    self.state.error_message = "Task cancelled"
                await asyncio.shield(self._finalize_execution({}))
            raise

        except Exception as e:
            workflow.logger.error(f"Workflow execution failed: {e}")
            await self._handle_workflow_error(e)
            raise

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
    def get_pending_escalations(self) -> list[dict[str, Any]]:
        """Unresolved escalations with the exact arguments awaiting a decision.

        The event log redacts arguments (commands can carry inline secrets), so
        this is how an approver sees what they approve. Callers gate it on the
        authority to resolve the escalation; get_current_state never carries it.
        """
        return [
            {
                "escalation_id": escalation.escalation_id,
                "tool_name": escalation.tool_name,
                "tool_call_id": escalation.tool_call_id,
                "tool_args": escalation.tool_args,
                "approvers": escalation.approvers,
            }
            for escalation in self._pending_escalations.values()
            if not escalation.resolved
        ]

    @workflow.query
    def get_current_state(self) -> dict[str, Any]:
        """Get current workflow state."""
        return {
            "status": self.state.status,
            "current_iteration": self.state.current_iteration,
            "success": self.state.success,
            "effective_policy": self.state.effective_policy,
            "cost": serialize_money(self.budget_tracker.cost) if self.budget_tracker else "0",
            "budget_remaining": (
                serialize_money(self.budget_tracker.get_remaining()) if self.budget_tracker else "0"
            ),
            "paused": self._paused,
            "pause_reason": self._pause_reason,
            "blocked_reason": self.state.blocked_reason,
            "validation_state": self.state.validation_state,
            "validation_repair_attempts": self.state.validation_repair_attempts,
            "waiting_for_continuation": self._waiting_for_continuation,
            "continuation_failure_reason": self._continuation_failure_reason,
            "continuation_message": self._continuation_message,
            "continuation_count": self._continuation_count,
            "pending_escalations": {
                eid: {
                    "tool_name": e.tool_name,
                    "tool_call_id": e.tool_call_id,
                    "resolved": e.resolved,
                }
                for eid, e in self._pending_escalations.items()
            },
            "pending_input_requests": {
                input_id: {
                    "resolved": bool(pending.get("resolved")),
                    "questions": pending.get("questions") or [],
                }
                for input_id, pending in self._pending_input_requests.items()
            },
            "context": self.context_manager.get_status() if self.context_manager else None,
        }
