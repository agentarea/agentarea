"""Running a capability tool through its activity, with governance verdicts."""

from typing import Any

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
from ..constants import (
    DEFAULT_RETRY_ATTEMPTS,
    HEARTBEAT_TIMEOUT,
    TOOL_EXECUTION_TIMEOUT,
    Activities,
    EventTypes,
)
from ..retry import make_retry_policy
from .approval import ToolApprovalMixin
from .context_tools import ContextToolsMixin
from .patches import GOVERNANCE_VERDICT_PATCH


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


class ToolExecutionMixin(ToolApprovalMixin, ContextToolsMixin):
    """Running a capability tool through its activity, with governance verdicts."""

    async def _execute_mcp_tool(self, tool_call: ToolCall) -> None:
        """Execute a single MCP tool call using Pydantic models."""
        tool_name = tool_call.function["name"]

        # Parse arguments
        import json

        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError):
            tool_args = {}

        # Single policy enforcement point (allow / deny / require-approval).
        if not await self._gate_tool_call(tool_call):
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
            )

            result_obj = await self._execute_governed_tool(
                tool_call, tool_name, tool_args, mcp_request
            )
            if result_obj is None:
                return

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
                    },
                )
                await self._publish_events_immediately()
                return

            if service_cost > ZERO:
                self.state.service_cost_used += service_cost

            # Offload large outputs to MinIO (hybrid/dynamic strategy)
            result_text = await self._maybe_offload_output(result_text, tool_call.id)

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
            return await workflow.execute_activity(
                Activities.EXECUTE_MCP_TOOL,
                args=[mcp_request],
                start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )
        except ActivityError as error:
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
            await self._deny_tool_call(tool_call, tool_name, reason, ran=ran)
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
