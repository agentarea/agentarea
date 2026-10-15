"""Stopping a run mid-call: the call is told to stop, and what it did is recorded."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, cast

from temporalio import workflow
from temporalio.exceptions import ActivityError, is_cancelled_exception
from temporalio.workflow import ActivityCancellationType

with workflow.unsafe.imports_passed_through():
    from agentarea_common.constants import MANAGED_BY_PLATFORM
    from agentarea_common.money import ZERO, Money, serialize_money, to_money

    from ..helpers import sanitize_tool_event_value
    from ..models import ToolCall

from ...models import LLMCallRequest, MCPToolRequest, UpdateTaskStatusRequest
from ..constants import (
    DEFAULT_RETRY_ATTEMPTS,
    HEARTBEAT_TIMEOUT,
    LLM_CALL_TIMEOUT,
    TOOL_EXECUTION_TIMEOUT,
    Activities,
    EventTypes,
)
from ..retry import make_retry_policy, model_call_retry_policy
from .budget import BudgetMixin
from .patches import (
    STOP_SETTLES_IN_FLIGHT_TOOL_PATCH,
    STOP_SETTLES_MODEL_CALL_PATCH,
    STOPPED_MODEL_CALL_IS_NOT_A_FAILURE_PATCH,
)

STOPPED_WHILE_RUNNING = (
    "Stopped by the user while this call was running. Whether it finished, and what it "
    "returned, is not known to this conversation; check before relying on its effects."
)
STOPPED_BEFORE_RUNNING = "Not executed: the user stopped the run before this call ran."


@dataclass
class StoppedToolCall:
    """A tool call whose activity was still running when the run was stopped."""

    tool_call: ToolCall
    handle: asyncio.Future[Any]


@dataclass
class StoppedModelCall:
    """A model call that was still running when the run was stopped."""

    iteration: int
    handle: asyncio.Future[Any]


def stopped_tool_event(tool_call: ToolCall, outcome: dict[str, Any]) -> dict[str, Any]:
    """The tool.result of a call that settled after the stop, and what it cost.

    ``outcome`` is the activity's result. The costs are the ones a call that
    finished normally adds to the run: a platform model it called, a call on a
    platform-funded connection, and a paid service.
    """
    model_cost = to_money(outcome.get("model_cost"))
    platform_funded = outcome.get("managed_by") == MANAGED_BY_PLATFORM
    paid_cost = to_money(outcome.get("cost")) if platform_funded else ZERO
    success = bool(outcome.get("success", True))
    text = outcome.get("result")
    if text is None:
        text = outcome.get("output", "")
    event: dict[str, Any] = {
        "tool_name": tool_call.function["name"],
        "tool_call_id": tool_call.id,
        "success": success,
        "cancelled": True,
        "exit_code": outcome.get("exit_code"),
        "service_cost": serialize_money(to_money(outcome.get("service_cost"))),
    }
    if success:
        event["result"] = sanitize_tool_event_value(str(text or ""), field_name="result")
    else:
        event["error"] = sanitize_tool_event_value(
            str(outcome.get("error") or text or "Tool execution failed"), field_name="result"
        )
    if model_cost > ZERO:
        event["model_cost"] = serialize_money(model_cost)
    if platform_funded:
        event["managed_by"] = MANAGED_BY_PLATFORM
        event["usage"] = outcome.get("usage")
        event["cost"] = serialize_money(paid_cost)
    return event


class ToolStopMixin(BudgetMixin):
    """Stopping a run mid-call: the call is told to stop, and what it did is recorded."""

    async def _run_model_activity(self, request: LLMCallRequest) -> Any:
        """Call the model; a stop of the run stops waiting for the call at once.

        The activity is told to stop and the call is kept, so the run can record
        what it cost once it settles, after the stop is final.
        """
        if not workflow.patched(STOP_SETTLES_MODEL_CALL_PATCH):
            return await workflow.execute_activity(
                Activities.CALL_LLM,
                args=[request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=model_call_retry_policy(),
            )
        # Cancelling the call tells the activity to stop and still delivers what
        # it ends with: a result if it finished, else its cancellation.
        handle = asyncio.ensure_future(
            workflow.execute_activity(
                Activities.CALL_LLM,
                args=[request],
                start_to_close_timeout=LLM_CALL_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=model_call_retry_policy(),
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        )
        try:
            return await asyncio.shield(handle)
        except asyncio.CancelledError:
            handle.cancel()
            self._stopped_model_call = StoppedModelCall(request.iteration or 0, handle)
            raise

    async def _run_tool_activity(self, tool_call: ToolCall, request: MCPToolRequest) -> Any:
        """Run the tool's activity; a stop of the run stops waiting for it at once.

        The activity is told to stop and the call is kept, so the run can record
        what it returned and cost once it settles, after the stop is final.
        """
        if not workflow.patched(STOP_SETTLES_IN_FLIGHT_TOOL_PATCH):
            return await workflow.execute_activity(
                Activities.EXECUTE_MCP_TOOL,
                args=[request],
                start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
            )
        handle = asyncio.ensure_future(
            workflow.execute_activity(
                Activities.EXECUTE_MCP_TOOL,
                args=[request],
                start_to_close_timeout=TOOL_EXECUTION_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=make_retry_policy(DEFAULT_RETRY_ATTEMPTS),
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        )
        try:
            return await asyncio.shield(handle)
        except asyncio.CancelledError:
            handle.cancel()
            self._stopped_tool_calls.append(StoppedToolCall(tool_call, handle))
            raise

    async def _settle_stopped_work(self, final_status: str) -> None:
        """Wait for the calls the stop interrupted, record each one flagged cancelled.

        A call that finished before it heard of the stop still did its work and
        may have cost money; that is recorded, and the task's total with it, so
        nothing lands later without a trace of when it happened. The run's
        execution ends once they are recorded.
        """
        if not self._has_stopped_work():
            return
        stopped_tools, self._stopped_tool_calls = self._stopped_tool_calls, []
        stopped_model, self._stopped_model_call = self._stopped_model_call, None
        spent = ZERO
        if stopped_model is not None:
            spent += await self._settle_stopped_model_call(stopped_model)
        for call in stopped_tools:
            spent += await self._settle_stopped_tool_call(call)
        await self._publish_events_immediately()
        if spent > ZERO:
            self._budget.add_cost(spent)
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
                    workspace_id=self.state.workspace_id,
                    total_cost=self._budget.cost,
                    own_cost=self._own_cost,
                    tokens_used=self.state.tokens_used,
                )
            )
        self._add_execution_finished_event(execution_cancelled=True)
        await self._publish_events_immediately()

    async def _settle_stopped_model_call(self, call: StoppedModelCall) -> Money:
        """Record the interrupted model call, and what it cost when the provider said."""
        model_id = self.state.agent_config.get("model_id")
        try:
            result = await call.handle
        except ActivityError as error:
            if is_cancelled_exception(error) and workflow.patched(
                STOPPED_MODEL_CALL_IS_NOT_A_FAILURE_PATCH
            ):
                self._events.add_event(
                    EventTypes.LLM_CALL_COMPLETED,
                    {
                        "iteration": call.iteration,
                        "model_id": model_id,
                        "model_name": (self.state.resolved_model or {}).get("model_name"),
                        "cancelled": True,
                        "interrupted": True,
                        # Cut off before the provider reported usage: the call may
                        # have been billed, by an amount nobody knows.
                        "cost": None,
                        "cost_known": False,
                        "content": "",
                        "tool_calls": [],
                        "role": "assistant",
                    },
                )
                return ZERO
            self._events.add_event(
                EventTypes.LLM_CALL_FAILED,
                {
                    "iteration": call.iteration,
                    "model_id": model_id,
                    "cancelled": True,
                    # Cut off before the provider reported usage: the call may
                    # have been billed, by an amount nobody knows.
                    "cost": None,
                    "cost_known": False,
                    "error": "Stopped before the model replied; what the call cost is not known."
                    if is_cancelled_exception(error)
                    else sanitize_tool_event_value(str(error.cause or error), field_name="result"),
                },
            )
            return ZERO
        dump = getattr(result, "model_dump", None)
        outcome = cast(dict[str, Any], dump() if callable(dump) else dict(result))
        cost = to_money(outcome.get("cost"))
        usage = outcome.get("usage") or {}
        self.state.tokens_used += int(usage.get("total_tokens") or 0)
        provider_cost = outcome.get("provider_cost_usd")
        self._events.add_event(
            EventTypes.LLM_CALL_COMPLETED,
            {
                "iteration": call.iteration,
                "model_id": model_id,
                "model_name": (self.state.resolved_model or {}).get("model_name"),
                "managed_by": outcome.get("managed_by"),
                "cancelled": True,
                # The stop cut the reply short after the provider reported usage.
                "interrupted": bool(outcome.get("interrupted")),
                "cost": serialize_money(cost),
                "provider_cost_usd": serialize_money(to_money(provider_cost))
                if provider_cost is not None
                else None,
                "usage": {"cost": serialize_money(cost), "usage": usage},
                "content": outcome.get("content") or "",
                "thinking": outcome.get("thinking") or "",
                # The stop came before any of these ran; they never will.
                "tool_calls": [],
                "role": "assistant",
            },
        )
        return cost

    async def _settle_stopped_tool_call(self, call: StoppedToolCall) -> Money:
        """Record the interrupted tool call: what it returned and cost, if it finished."""
        try:
            result = await call.handle
        except ActivityError as error:
            self._events.add_event(
                EventTypes.TOOL_CALL_FAILED,
                {
                    "tool_name": call.tool_call.function["name"],
                    "tool_call_id": call.tool_call.id,
                    "success": False,
                    "cancelled": True,
                    "error": "Stopped before the call finished."
                    if is_cancelled_exception(error)
                    else sanitize_tool_event_value(str(error.cause or error), field_name="result"),
                    "iteration": self.state.current_iteration,
                },
            )
            return ZERO
        dump = getattr(result, "model_dump", None)
        outcome = cast(dict[str, Any], dump() if callable(dump) else dict(result))
        event = stopped_tool_event(call.tool_call, outcome)
        self.state.service_cost_used += to_money(event["service_cost"])
        event["iteration"] = self.state.current_iteration
        self._events.add_event(EventTypes.TOOL_CALL_COMPLETED, event)
        return to_money(event.get("model_cost")) + to_money(event.get("cost"))
