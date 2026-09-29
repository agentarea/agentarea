"""The tool-call policy gate: allow, deny, or pause for human approval."""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from ..helpers import (
        ToolAction,
        approvers_for_tool,
        decide_tool_action,
        sanitize_tool_event_value,
        tool_definition_name,
        tool_policy_aliases,
    )
    from ..models import Message, PendingEscalation, ToolCall

from ...models import UpdateTaskStatusRequest
from ..constants import (
    ACTIVITY_TIMEOUT,
    DEFAULT_RETRY_ATTEMPTS,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import make_retry_policy
from .budget import BudgetMixin
from .patches import APPROVAL_RESPONSE_ONCE_PATCH


class ToolApprovalMixin(BudgetMixin):
    """The tool-call policy gate: allow, deny, or pause for human approval."""

    async def _deny_tool_call(
        self, tool_call: ToolCall, tool_name: str, reason: str, ran: bool = False
    ) -> None:
        """Reject a tool call by policy and surface the reason to the LLM.

        ``ran`` marks a gate that judged the call's output: the call executed,
        only its result is kept from the model.
        """
        workflow.logger.warning(f"Tool '{tool_name}' denied by policy: {reason}")
        message = (
            f"Tool call ran, but its result was withheld by policy: {reason}"
            if ran
            else f"Tool call denied by policy: {reason}"
        )
        self.state.messages.append(
            Message(
                role="tool",
                content=message,
                tool_call_id=tool_call.id,
                name=tool_name,
            )
        )
        # A denial is an outcome of the call, not just a log line: emit it so
        # watchers see a denied tool instead of a call that never resolves.
        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "success": False,
                "iteration": self.state.current_iteration,
                "error": message,
                "denied_by_policy": True,
            },
        )

    async def _require_tool_approval(
        self, tool_call: ToolCall, tool_name: str, tool_args: dict, reason: str | None = None
    ) -> bool:
        """Run the human-in-the-loop escalation flow. Returns True if approved."""
        if (
            self._interaction_contract_enabled
            and not self.state.interaction_capabilities.allow_approvals
        ):
            await self._deny_tool_call(
                tool_call,
                tool_name,
                "Required human approval is unavailable on this return route. The operation "
                "was not executed. Use permitted alternatives; if approval is indispensable, "
                "complete with outcome='blocked' and explain the missing authorization.",
            )
            return False
        escalation_id = str(workflow.uuid4())
        escalation = PendingEscalation(
            escalation_id=escalation_id,
            tool_call_id=tool_call.id,
            tool_name=tool_name,
            tool_args=tool_args,
            approvers=approvers_for_tool(
                self.state.effective_policy,
                tool_name,
                tool_policy_aliases(self.state.mcp_tool_routes, tool_name),
            ),
        )
        self._pending_escalations[escalation_id] = escalation
        self.state.status = ExecutionStatus.WAITING_FOR_APPROVAL

        # Persist approval status to DB so inbox can query it
        await workflow.execute_activity(
            Activities.UPDATE_TASK_STATUS,
            args=[
                UpdateTaskStatusRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    status="waiting_for_approval",
                    workspace_id=self.state.workspace_id,
                )
            ],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
        )

        self._events.add_event(
            EventTypes.HUMAN_APPROVAL_REQUESTED,
            {
                "escalation_id": escalation_id,
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "iteration": self.state.current_iteration,
                "arguments": sanitize_tool_event_value(tool_args),
                "approvers": escalation.approvers,
                "message": f"Tool '{tool_name}' requires human approval"
                + (f": {reason}" if reason else ""),
            },
        )
        await self._publish_events_immediately()

        # Wait for THIS specific escalation to be resolved
        await workflow.wait_condition(lambda: escalation.resolved)

        approved = escalation.approved
        if approved:
            await self._check_monthly_spend_cap()
        one_response = workflow.patched(APPROVAL_RESPONSE_ONCE_PATCH)
        if one_response:
            self._events.add_event(
                EventTypes.HUMAN_APPROVAL_RECEIVED
                if approved
                else EventTypes.HUMAN_APPROVAL_DENIED,
                {
                    "escalation_id": escalation_id,
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "iteration": self.state.current_iteration,
                    "approved": bool(approved),
                    "approved_by": escalation.approved_by,
                    "comment": escalation.comment,
                },
            )
        if not approved:
            deny_msg = escalation.deny_comment or "Denied by user"
            if not one_response:
                self._events.add_event(
                    EventTypes.HUMAN_APPROVAL_DENIED,
                    {
                        "escalation_id": escalation_id,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "iteration": self.state.current_iteration,
                        "comment": deny_msg,
                    },
                )
            self._events.add_event(
                EventTypes.TOOL_CALL_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "success": False,
                    "iteration": self.state.current_iteration,
                    "error": f"Denied by human operator: {deny_msg}",
                    "denied_by_human": True,
                },
            )
            await self._publish_events_immediately()
            self.state.messages.append(
                Message(
                    role="tool",
                    content=f"Tool call denied by human operator: {deny_msg}",
                    tool_call_id=tool_call.id,
                    name=tool_name,
                )
            )
        else:
            if not one_response:
                self._events.add_event(
                    EventTypes.HUMAN_APPROVAL_RECEIVED,
                    {
                        "escalation_id": escalation_id,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        "iteration": self.state.current_iteration,
                    },
                )
            await self._publish_events_immediately()

        # Clean up and restore running status once no escalations remain
        del self._pending_escalations[escalation_id]
        if not self._pending_escalations:
            self.state.status = ExecutionStatus.EXECUTING
            await workflow.execute_activity(
                Activities.UPDATE_TASK_STATUS,
                args=[
                    UpdateTaskStatusRequest(
                        user_context_data=self.state.user_context_data,
                        task_id=self.state.task_id,
                        status="running",
                        workspace_id=self.state.workspace_id,
                    )
                ],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )
        if approved and self._monthly_cap_message:
            await self._deny_tool_call(tool_call, tool_name, self._monthly_cap_message)
            return False
        return bool(approved)

    async def _gate_tool_call(self, tool_call: ToolCall) -> bool:
        """Single policy enforcement point applied to EVERY capability tool call.

        Returns True if the call may proceed; False if it was denied by policy
        or its approval was rejected (a tool message has already been appended
        so the LLM sees the outcome).
        """
        import json

        tool_name = tool_call.function["name"]
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        if self._monthly_cap_message:
            await self._deny_tool_call(tool_call, tool_name, self._monthly_cap_message)
            return False

        # The model may only call what it was offered: a name it invented, recalled
        # from earlier context, or read in a skill never reaches an executor.
        offered = {name for t in self.state.available_tools if (name := tool_definition_name(t))}
        if tool_name not in offered:
            await self._deny_tool_call(tool_call, tool_name, "tool is not available to this agent")
            return False

        decision = decide_tool_action(
            self.state.effective_policy,
            tool_name,
            tool_policy_aliases(self.state.mcp_tool_routes, tool_name),
        )
        workflow.logger.info(f"Tool '{tool_name}' policy decision: {decision.value}")

        if decision is ToolAction.DENY:
            await self._deny_tool_call(tool_call, tool_name, "not permitted by policy")
            return False
        if decision is ToolAction.REQUIRE_APPROVAL:
            return await self._require_tool_approval(tool_call, tool_name, tool_args)
        return True
