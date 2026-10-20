"""Running a capability tool through its activity, with governance verdicts."""

from typing import Any, cast

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from agentarea_common.money import ZERO, serialize_money, to_money
    from agentarea_governance.domain.exceptions import (
        EscalationRequiredError,
        GovernanceDeniedError,
    )

    from ..helpers import sanitize_tool_event_value
    from ..models import Message, ToolCall

from ...models import MCPToolRequest
from ..constants import EventTypes
from .approval import ToolApprovalMixin
from .context_tools import ContextToolsMixin
from .patches import GOVERNANCE_VERDICT_PATCH
from .stopping import ToolStopMixin


def _governance_verdict(error: ActivityError) -> tuple[str, str, bool] | None:
    """The governance gate verdict an activity failed with, as (type, reason, ran).

    The reason reads "<gate>: <why>"; ``ran`` is whether the gate judged the
    call's output, i.e. the call had already executed. A worker on an older
    bridge sends no details, or details without a phase; its verdict reads as a
    denial before the call, as it always has.
    """
    cause = error.cause
    if not isinstance(cause, ApplicationError) or cause.type not in (
        GovernanceDeniedError.__name__,
        EscalationRequiredError.__name__,
    ):
        return None
    if not cause.details:
        return cause.type, cause.message, False
    verdict = cause.details[0]
    ran = str(verdict.get("phase", "")).startswith("post_")
    return cause.type, f"{verdict['interceptor_name']}: {verdict['reason']}", ran


def structured_content_field(result: dict[str, Any]) -> dict[str, Any]:
    """The tool.result keys for an MCP tool's ``structuredContent``.

    Absent when the tool returned none, so events of other tools and older
    histories keep their shape.
    """
    if result.get("structured_content") is not None:
        return {"structured_content": result["structured_content"]}
    if result.get("structured_content_dropped"):
        return {"structured_content_dropped": True}
    return {}


def tool_images_field(result: dict[str, Any]) -> dict[str, Any]:
    """The tool.result key for images the tool returned: references, never bytes."""
    return {"images": result["images"]} if result.get("images") else {}


class ToolExecutionMixin(ToolApprovalMixin, ContextToolsMixin, ToolStopMixin):
    """Running a capability tool through its activity, with governance verdicts."""

    async def _execute_mcp_tool(self, tool_call: ToolCall) -> None:
        """Execute a single MCP tool call using Pydantic models."""
        tool_name = tool_call.function["name"]

        # Parse arguments
        import json

        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except json.JSONDecodeError, KeyError:
            tool_args = {}

        # Single policy enforcement point (allow / deny / require-approval).
        allowed, policy_approval_granted = await self._gate_tool_call(tool_call)
        if not allowed:
            return

        # Publish tool call started event (only after approval if required)
        self._events.add_event(
            EventTypes.TOOL_CALL_STARTED,
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call.id,
                "iteration": self.state.current_iteration,
                "arguments": sanitize_tool_event_value(tool_args),
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

            mcp_route = self.state.mcp_tool_routes.get(tool_name)
            mcp_request = MCPToolRequest(
                tool_name=tool_name,
                tool_args=tool_args,
                server_instance_id=UUID(mcp_route.instance_id) if mcp_route else None,
                mcp_route=mcp_route,
                workspace_id=workspace_id,
                user_id=self.state.user_context_data.get("user_id"),
                user_context_data=self.state.user_context_data,
                task_id=str(self.state.task_id),
                execution_id=self.state.execution_id,
                tool_call_id=tool_call.id,
                agent_id=UUID(self.state.agent_id) if self.state.agent_id else None,
                tools=self.state.agent_config.get("tools"),
                metadata=self._workflow_metadata or {},
                effective_policy=self.state.effective_policy,
                cost_used=self.budget_tracker.cost if self.budget_tracker else None,
                tokens_used=self.state.tokens_used,
                service_cost_used=self.state.service_cost_used,
                policy_approval_granted=policy_approval_granted,
                openapi_operation_tools=self.state.agent_config.get("openapi_operation_tools")
                or {},
            )

            started = workflow.now() if self._task_log_on() else None
            started_at = started.isoformat() if started else None
            result_obj = await self._execute_governed_tool(
                tool_call, tool_name, tool_args, mcp_request
            )
            if result_obj is None:
                return

            # Normalize result to a dict for robust access
            result_dict: dict[str, Any]
            model_dump = getattr(result_obj, "model_dump", None)
            if callable(model_dump):
                try:
                    result_dict = cast(dict[str, Any], model_dump())
                except Exception:
                    result_dict = {}
            elif isinstance(result_obj, dict):
                result_dict = result_obj
            else:
                result_dict = getattr(result_obj, "__dict__", {}) or {}

            # Extract fields with fallbacks
            success = bool(result_dict.get("success", getattr(result_obj, "success", True)))
            error_text = result_dict.get("error", getattr(result_obj, "error", None))
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
            service_cost = to_money(
                result_dict.get("service_cost", getattr(result_obj, "service_cost", None))
            )
            # A platform model the tool called (image, video, decision), already
            # priced in the billing currency: it is inference spend, so it joins the
            # run budget and task total as an LLM call does, and the event carries it
            # for the task_summary rollup. Charged whether or not the tool then
            # succeeded, since the provider was paid either way. Absent in older
            # histories, so replays take no new branch.
            model_cost = to_money(result_dict.get("model_cost"))
            # A call whose connector declares its cost, metered by the activity's
            # tool-call layer in the billing currency: it joins the run budget and
            # task total the same way, and the event says on whose key it ran and
            # whether its ledger lines are written (``cost_metered``), so they are
            # not derived from the event again. Absent in older histories.
            paid_cost = to_money(result_dict.get("cost"))
            priced_cost_fields: dict[str, Any] = (
                {"model_cost": serialize_money(model_cost)} if model_cost > ZERO else {}
            )
            # Absent in older histories, like model_cost.
            if result_dict.get("model_billing"):
                priced_cost_fields["model_billing"] = result_dict["model_billing"]
            if result_dict.get("cost_unknown"):
                priced_cost_fields["cost_unknown"] = True
            paid_call_fields: dict[str, Any] = {}
            if paid_cost > ZERO:
                paid_call_fields["cost"] = serialize_money(paid_cost)
            if result_dict.get("payer"):
                paid_call_fields["payer"] = result_dict["payer"]
            if result_dict.get("cost_metered"):
                paid_call_fields["cost_metered"] = True
            # A retried call says so, on success and failure alike; absent on a first
            # attempt, so the event of every call that was not replayed is unchanged.
            replay_fields: dict[str, Any] = {}
            if result_dict.get("replayed"):
                replay_fields["replayed"] = True
            if result_dict.get("attempt"):
                replay_fields["attempt"] = result_dict["attempt"]
            tool_meta = {
                "exit_code": result_dict.get("exit_code"),
                "duration": execution_time
                if execution_time is not None or started is None
                else (workflow.now() - started).total_seconds(),
                "server": result_dict.get("server_name") or result_dict.get("server_instance_id"),
                "started_at": started_at,
                "artifact_paths": result_dict.get("artifact_paths") or [],
            }
            if model_cost + paid_cost > ZERO:
                if self.budget_tracker is None:
                    raise RuntimeError("Workflow budget tracker is not initialized")
                self.budget_tracker.add_cost(model_cost + paid_cost)
                self.state.llm_cost_used += model_cost
                self._enforce_agent_spend_cap()

            # Failure path: surface the error to the LLM and emit ToolCallFailed
            # so the UI renders an actual error instead of "(no result data)".
            if not success:
                error_message = error_text or result_text or "Tool execution failed"
                workflow.logger.warning(f"Tool '{tool_name}' returned failure: {error_message}")
                self.state.messages.append(
                    Message(
                        role="tool",
                        content=f"Tool failed: {error_message}",
                        tool_call_id=tool_call.id,
                        name=tool_name,
                        meta=tool_meta,
                    )
                )
                self._events.add_event(
                    EventTypes.TOOL_CALL_FAILED,
                    {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.id,
                        # Say it outright: a consumer should not have to infer
                        # failure from the presence of an error field.
                        "success": False,
                        "error": sanitize_tool_event_value(error_message, field_name="result"),
                        "exit_code": result_dict.get("exit_code"),
                        "artifact_paths": result_dict.get("artifact_paths") or [],
                        "arguments": sanitize_tool_event_value(tool_args),
                        "execution_time": execution_time,
                        "iteration": self.state.current_iteration,
                        "source": result_dict.get("source"),
                        "server_instance_id": result_dict.get("server_instance_id"),
                        "server_name": result_dict.get("server_name"),
                        "server_icon": result_dict.get("server_icon"),
                        **priced_cost_fields,
                        **replay_fields,
                    },
                )
                await self._publish_events_immediately()
                return

            if service_cost > ZERO:
                self.state.service_cost_used += service_cost
                self._enforce_agent_spend_cap()

            # Offload large outputs to MinIO (hybrid/dynamic strategy)
            result_text = await self._maybe_offload_output(result_text, tool_call.id)

            # Add tool result to conversation
            self.state.messages.append(
                Message(
                    role="tool",
                    content=result_text,
                    tool_call_id=tool_call.id,
                    name=tool_name,
                    attachments=result_dict.get("images") or None,
                    meta=tool_meta,
                )
            )

            # Publish tool completion event
            self._events.add_event(
                EventTypes.TOOL_CALL_COMPLETED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "success": success,
                    # The command's own verdict, so the UI and the rollups stop
                    # having to guess it out of the result text.
                    "exit_code": result_dict.get("exit_code"),
                    "artifact_paths": result_dict.get("artifact_paths") or [],
                    "iteration": self.state.current_iteration,
                    "result": sanitize_tool_event_value(result_text, field_name="result"),
                    "arguments": sanitize_tool_event_value(tool_args),
                    "execution_time": execution_time,
                    "service_cost": serialize_money(service_cost),
                    **priced_cost_fields,
                    **paid_call_fields,
                    **replay_fields,
                    **structured_content_field(result_dict),
                    **tool_images_field(result_dict),
                    "payment": result_dict.get("payment"),
                    "source": result_dict.get("source"),
                    "server_instance_id": result_dict.get("server_instance_id"),
                    "server_name": result_dict.get("server_name"),
                    "server_icon": result_dict.get("server_icon"),
                },
            )
            await self._publish_events_immediately()

            workflow.logger.info(f"MCP tool '{tool_name}' executed successfully")

        except Exception as e:
            if self._is_cancellation(e):
                raise
            workflow.logger.error(f"MCP tool call {tool_name} failed: {e}", exc_info=True)

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
            self._events.add_event(
                EventTypes.TOOL_CALL_FAILED,
                {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call.id,
                    "error": sanitize_tool_event_value(str(e), field_name="result"),
                    "iteration": self.state.current_iteration,
                },
            )
            await self._publish_events_immediately()

    async def _execute_governed_tool(
        self,
        tool_call: ToolCall,
        tool_name: str,
        tool_args: dict[str, Any],
        mcp_request: MCPToolRequest,
    ) -> Any | None:
        """Run the tool activity and act on a governance gate's verdict on it.

        A gate DENY reaches the model as a policy denial. A gate ESCALATE pauses
        for a human through the same approval flow as ApprovalPolicy; on approval
        the same call is re-issued with the approval recorded, and the gate that
        escalated decides whether that satisfies it. Returns None when the call
        did not run — the tool message is already in the conversation.
        """
        try:
            return await self._run_tool_activity(tool_call, mcp_request)
        except ActivityError as error:
            if self._is_cancellation(error):
                raise
            verdict = _governance_verdict(error)
            # An escalation of a call a human already approved is not asked
            # twice; it fails the call like any other activity error.
            if (
                verdict is None
                or (
                    verdict[0] == EscalationRequiredError.__name__
                    and mcp_request.escalation_approved
                )
                or not workflow.patched(GOVERNANCE_VERDICT_PATCH)
            ):
                raise
        verdict_type, reason, ran = verdict

        if verdict_type == GovernanceDeniedError.__name__:
            await self._deny_tool_call(tool_call, tool_name, reason, ran=ran, announced=True)
            await self._publish_events_immediately()
            return None

        if not await self._require_tool_approval(tool_call, tool_name, tool_args, reason):
            await self._publish_events_immediately()
            return None
        return await self._execute_governed_tool(
            tool_call,
            tool_name,
            tool_args,
            mcp_request.model_copy(update={"escalation_approved": True}),
        )
