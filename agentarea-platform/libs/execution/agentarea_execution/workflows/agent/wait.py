"""The wait tool: idling on a durable timer instead of a worker or a sandbox."""

import asyncio
import json
from datetime import timedelta
from enum import StrEnum

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from agentarea_governance.domain.tool_calls import WAIT_TOOL_NAME

    from ..models import Message, ToolCall

from ..constants import EventTypes
from .base import AgentWorkflowBase

WAIT_MIN_SECONDS = 1
WAIT_MAX_SECONDS = 900


class WaitWakeReason(StrEnum):
    """Why a wait ended before its timer fired."""

    USER_MESSAGE = "user_message"
    PAUSE = "pause"


class WaitMixin(AgentWorkflowBase):
    """The wait tool: idling on a durable timer instead of a worker or a sandbox."""

    def _wait_interruption(self) -> WaitWakeReason | None:
        if self._paused:
            return WaitWakeReason.PAUSE
        if self._message_queue or (self._interaction_contract_enabled and self._a2ui_action_queue):
            return WaitWakeReason.USER_MESSAGE
        return None

    async def _execute_wait(self, tool_call: ToolCall) -> None:
        try:
            tool_args = json.loads(tool_call.function["arguments"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            await self._reject_wait(tool_call, f"arguments must be valid JSON: {exc}")
            return
        if not isinstance(tool_args, dict):
            await self._reject_wait(tool_call, "arguments must be a JSON object")
            return
        seconds = tool_args.get("seconds")
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not WAIT_MIN_SECONDS <= seconds <= WAIT_MAX_SECONDS
        ):
            await self._reject_wait(
                tool_call,
                f"seconds must be an integer from {WAIT_MIN_SECONDS} to {WAIT_MAX_SECONDS}",
            )
            return
        reason = tool_args.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            await self._reject_wait(tool_call, "reason must be a non-empty string")
            return
        reason = reason.strip()
        arguments = {"seconds": seconds, "reason": reason}

        self._events.add_event(
            EventTypes.TOOL_CALL_STARTED,
            {
                "tool_name": WAIT_TOOL_NAME,
                "tool_call_id": tool_call.id,
                "iteration": self.state.current_iteration,
                "arguments": arguments,
            },
        )
        await self._publish_events_immediately()

        started_at = workflow.now()
        try:
            await workflow.wait_condition(
                lambda: self._wait_interruption() is not None,
                timeout=timedelta(seconds=seconds),
            )
        except TimeoutError:
            woken_by = None
        except asyncio.CancelledError:
            self._events.add_event(
                EventTypes.TOOL_CALL_FAILED,
                {
                    "tool_name": WAIT_TOOL_NAME,
                    "tool_call_id": tool_call.id,
                    "success": False,
                    "error": "The task was cancelled during the wait.",
                    "iteration": self.state.current_iteration,
                },
            )
            raise
        else:
            woken_by = self._wait_interruption()
        waited = int((workflow.now() - started_at).total_seconds())

        if woken_by is WaitWakeReason.USER_MESSAGE:
            content = (
                f"Wait for '{reason}' ended after {waited} of {seconds} s: a user message "
                "arrived. Read it before waiting again."
            )
        elif woken_by is WaitWakeReason.PAUSE:
            content = (
                f"Wait for '{reason}' ended after {waited} of {seconds} s: the task was paused."
            )
        else:
            content = f"Waited {waited} s for '{reason}'."
        self.state.messages.append(
            Message(role="tool", content=content, tool_call_id=tool_call.id, name=WAIT_TOOL_NAME)
        )
        self._events.add_event(
            EventTypes.TOOL_CALL_COMPLETED,
            {
                "tool_name": WAIT_TOOL_NAME,
                "tool_call_id": tool_call.id,
                "success": True,
                "iteration": self.state.current_iteration,
                "arguments": arguments,
                "result": content,
                "execution_time": waited,
                "waited_seconds": waited,
                "woken_by": woken_by,
            },
        )
        await self._publish_events_immediately()

    async def _reject_wait(self, tool_call: ToolCall, error: str) -> None:
        """Return a tool-paired contract error instead of guessing a duration."""
        self.state.messages.append(
            Message(
                role="tool",
                name=WAIT_TOOL_NAME,
                tool_call_id=tool_call.id,
                content=json.dumps(
                    {
                        "status": "invalid_wait_arguments",
                        "error": error,
                        "instruction": (
                            f"Call wait again with an integer seconds from {WAIT_MIN_SECONDS} "
                            f"to {WAIT_MAX_SECONDS} and a non-empty reason. Call it repeatedly "
                            "for longer waits."
                        ),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )
        self._events.add_event(
            EventTypes.TOOL_CALL_FAILED,
            {
                "tool_name": WAIT_TOOL_NAME,
                "tool_call_id": tool_call.id,
                "success": False,
                "error": error,
                "iteration": self.state.current_iteration,
            },
        )
        await self._publish_events_immediately()
