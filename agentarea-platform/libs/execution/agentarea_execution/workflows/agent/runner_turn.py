"""Turns on a client's runner: the agent's CLI (Codex, Claude Code) runs each turn.

A run of an agent on a client (ADR-0051) calls no model and no tool itself.
Each turn is one ``run_runner_turn`` activity on the client's own task queue,
which the API process holding the runner's socket polls; it completes when the
runner reports the turn finished, and heartbeats while the runner is connected,
so a lost runner fails the attempt and the turn is assigned again. What the CLI
does arrives as ``runner_turn_update`` signals and is recorded like any run's
events. A message sent during a turn is steered into it; the CLI's requests for
approval are the run's escalations, answered from the inbox. A pause stops the
CLI's turn; the resume starts the next turn on the same session.
"""

import asyncio
import json
from typing import Any
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError,
    TimeoutType,
    is_cancelled_exception,
)

with workflow.unsafe.imports_passed_through():
    from ..helpers import approvers_for_tool, sanitize_tool_event_value
    from ..models import Message, PendingEscalation

from ...models import (
    DeliverToRunnerRequest,
    RunnerActor,
    RunnerApprovalAsk,
    RunnerSteerOutcome,
    RunnerTurnEvent,
    RunnerTurnRequest,
    RunnerTurnResult,
    UpdateTaskStatusRequest,
    runner_task_queue,
)
from ..constants import (
    ACTIVITY_TIMEOUT,
    RUNNER_TURN_HEARTBEAT_TIMEOUT,
    RUNNER_TURN_MAX_ATTEMPTS,
    RUNNER_TURN_RETRY_DELAY,
    RUNNER_TURN_START_TIMEOUT,
    RUNNER_TURN_TIMEOUT,
    Activities,
    EventTypes,
    ExecutionStatus,
)
from ..retry import bookkeeping_retry_policy
from .base import AgentWorkflowBase

# What a runner reports when it lost its socket mid-turn; the turn is assigned again.
RUNNER_LOST = "RunnerLost"
# The turn after a resume, when nobody sent the paused run a message.
RESUME_MESSAGE = "You were paused. Continue from where you stopped."
# The turn a retry of a failed run sends, when the failed turn was not the first.
RETRY_MESSAGE = "Your last turn ended before it finished. Do it again from where you stopped."


class RunnerTurnMixin(AgentWorkflowBase):
    """One turn of the run on its client's CLI, and what the run hears during it."""

    @property
    def _on_runner(self) -> bool:
        return self._runner_client_id is not None

    async def _execute_runner_turn(self) -> None:
        """Send the turn's message to the runner and wait for the CLI to answer it."""
        queued = [*self._runner_held_back, *self._message_queue]
        self._runner_held_back = []
        self._message_queue.clear()
        if not self._conversation_seeded:
            if self.state.goal is None:
                raise ApplicationError(
                    "workflow goal is missing from execution state",
                    type="InvalidExecutionSnapshot",
                    non_retryable=True,
                )
            queued.insert(0, {"id": str(workflow.uuid4()), "content": self.state.goal.description})
            self._conversation_seeded = True
        if not queued and self._runner_retry_message is not None:
            # A retry re-runs the failed turn; the CLI's session holds what it was asked.
            text, self._runner_retry_message = self._runner_retry_message, None
            self._end_runner_turn(await self._run_runner_turn(text, None))
            return
        if not queued:
            raise ApplicationError(
                "A turn on a runner has no message to send; send the task a message instead",
                type="RunnerTurnWithoutMessage",
                non_retryable=True,
            )
        for message in queued:
            self.state.messages.append(Message(role="user", content=message["content"]))
        sender = next(
            (message["sender"] for message in reversed(queued) if message.get("sender")), None
        )
        result = await self._run_runner_turn(
            "\n\n".join(message["content"] for message in queued),
            RunnerActor.model_validate(sender) if sender else None,
        )
        self._end_runner_turn(result)

    def _end_runner_turn(self, result: RunnerTurnResult) -> None:
        self._settle_runner_turn()
        if result.status == "completed":
            self._complete_runner_turn(result.response or "")
            return
        raise ApplicationError(
            result.error
            or (
                "The CLI's turn was interrupted"
                if result.status == "interrupted"
                else "the CLI failed without saying why"
            ),
            type="RunnerTurnFailed",
            non_retryable=True,
        )

    async def _run_runner_turn(self, text: str, actor: RunnerActor | None) -> RunnerTurnResult:
        """The turn's activity, scheduled again whenever its runner is lost."""
        attempt = 0
        while True:
            attempt += 1
            self._runner_turn_key = f"{self.state.current_iteration}.{attempt}"
            self._runner_last_seq = 0
            self._runner_updates = []
            self._runner_seen_asks = set()
            await self._publish_events_immediately()
            handle = workflow.start_activity(
                Activities.RUN_RUNNER_TURN,
                RunnerTurnRequest(
                    task_id=UUID(self.state.task_id),
                    agent_id=UUID(self.state.agent_id),
                    workspace_id=self.state.workspace_id,
                    iteration=self.state.current_iteration,
                    turn_key=self._runner_turn_key,
                    message=text,
                    actor=actor,
                ),
                result_type=RunnerTurnResult,
                task_queue=runner_task_queue(str(self._runner_client_id)),
                schedule_to_start_timeout=RUNNER_TURN_START_TIMEOUT,
                start_to_close_timeout=RUNNER_TURN_TIMEOUT,
                heartbeat_timeout=RUNNER_TURN_HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            try:
                while not handle.done():
                    await workflow.wait_condition(
                        lambda handle=handle: handle.done() or self._runner_has_work()
                    )
                    await self._serve_runner_turn(deliver=True)
            except BaseException as error:
                await self._leave_runner_turn(handle, error)
                raise
            try:
                result = await handle
            except ActivityError as error:
                lost = self._runner_lost(error)
                await self._serve_runner_turn(deliver=False)
                await self._close_open_runner_tools(
                    "The runner was lost before it finished."
                    if lost
                    else "The turn ended before it finished."
                )
                await self._expire_runner_escalations(
                    "The runner was lost before a decision."
                    if lost
                    else "The turn ended before a decision."
                )
                if not lost:
                    reason = self._runner_turn_error(error)
                    if reason is None:
                        raise
                    raise reason from error
                if attempt >= RUNNER_TURN_MAX_ATTEMPTS:
                    raise ApplicationError(
                        f"The runner was lost {attempt} times during this turn",
                        type="RunnerTurnLost",
                        non_retryable=True,
                    ) from error
                workflow.logger.warning(
                    f"Runner of turn {self._runner_turn_key} was lost; assigning it again"
                )
                self._runner_held_back.extend(self._runner_steering.values())
                self._runner_steering.clear()
                await workflow.sleep(RUNNER_TURN_RETRY_DELAY)
                continue
            await self._serve_runner_turn(deliver=False)
            paused = self._runner_pausing and result.status == "interrupted"
            self._runner_pausing = False
            await self._close_open_runner_tools(
                "Paused before it finished."
                if paused
                else "Stopped before it finished."
                if result.status == "interrupted"
                else "The turn ended before it finished."
            )
            await self._expire_runner_escalations(
                "The run was paused before a decision."
                if paused
                else "The turn ended before a decision."
            )
            if not paused:
                self._runner_turn_key = None
                return result
            await workflow.wait_condition(lambda: not self._paused)
            text, actor = self._runner_resumed_turn(actor)

    async def _leave_runner_turn(
        self, handle: workflow.ActivityHandle[RunnerTurnResult], error: BaseException
    ) -> None:
        """The run leaves a turn the CLI still works on: the activity stops the CLI's turn.

        On a stop, what the runner reported until then is recorded before the run closes.
        """
        handle.cancel()
        try:
            await handle
        except ActivityError as stopped:
            if not is_cancelled_exception(stopped):
                workflow.logger.warning(
                    f"Turn {self._runner_turn_key} ended with an error while it was stopped",
                    exc_info=True,
                )
        if isinstance(error, asyncio.CancelledError) or is_cancelled_exception(error):
            await self._serve_runner_turn(deliver=False)
            await self._close_open_runner_tools("Stopped before it finished.")
        self._runner_turn_key = None
        self._runner_updates = []

    @staticmethod
    def _runner_lost(error: ActivityError) -> bool:
        cause = error.cause
        if isinstance(cause, TimeoutError):
            return cause.type == TimeoutType.HEARTBEAT
        return isinstance(cause, ApplicationError) and cause.type == RUNNER_LOST

    @staticmethod
    def _runner_turn_error(error: ActivityError) -> ApplicationError | None:
        """Why a turn timed out, in words a person can act on."""
        cause = error.cause
        if isinstance(cause, TimeoutError) and cause.type == TimeoutType.SCHEDULE_TO_START:
            minutes = int(RUNNER_TURN_START_TIMEOUT.total_seconds() // 60)
            return ApplicationError(
                f"No runner of the agent's client took the turn within {minutes} minutes; "
                + "start the client's runner and send the task a message",
                type="RunnerOffline",
                non_retryable=True,
            )
        if isinstance(cause, TimeoutError) and cause.type == TimeoutType.START_TO_CLOSE:
            hours = int(RUNNER_TURN_TIMEOUT.total_seconds() // 3600)
            return ApplicationError(
                f"The CLI's turn ran longer than {hours} hours",
                type="RunnerTurnTimedOut",
                non_retryable=True,
            )
        return None

    def _runner_has_work(self) -> bool:
        if self._runner_pausing:
            # Messages wait for the turn after the resume; answers die with the paused turn.
            return bool(self._runner_updates)
        answered = any(
            escalation.resolved
            for escalation_id, escalation in self._pending_escalations.items()
            if escalation_id in self._runner_asks
        )
        return bool(self._runner_updates) or bool(self._message_queue) or answered or self._paused

    def _runner_resumed_turn(self, actor: RunnerActor | None) -> tuple[str, RunnerActor | None]:
        """What the turn after a resume sends: the messages since the pause, else a nudge."""
        queued = [*self._runner_held_back, *self._runner_steering.values(), *self._message_queue]
        self._runner_held_back = []
        self._runner_steering.clear()
        self._message_queue.clear()
        if not queued:
            return RESUME_MESSAGE, actor
        for message in queued:
            self.state.messages.append(Message(role="user", content=message["content"]))
        sender = next(
            (message["sender"] for message in reversed(queued) if message.get("sender")), None
        )
        return (
            "\n\n".join(message["content"] for message in queued),
            RunnerActor.model_validate(sender) if sender else actor,
        )

    async def _serve_runner_turn(self, *, deliver: bool) -> None:
        """Record what the runner reported, and send it the messages and answers since."""
        updates, self._runner_updates = self._runner_updates, []
        for update in updates:
            if update.turn_key != self._runner_turn_key:
                continue
            if update.actor is not None:
                self._runner_actor = update.actor
            for event in update.events:
                if event.seq <= self._runner_last_seq:
                    continue
                self._runner_last_seq = event.seq
                self._record_runner_event(event)
            for ask in update.approvals:
                await self._open_runner_escalation(ask)
            for outcome in update.steers:
                self._settle_steer(outcome)
        if deliver and self._paused and not self._runner_pausing:
            self._runner_pausing = True
            await self._deliver_to_runner(kind="pause")
        if deliver and not self._runner_pausing:
            for message in list(self._message_queue):
                self._message_queue.remove(message)
                self._runner_steering[message["id"]] = message
                await self._deliver_to_runner(
                    kind="steer", message_id=message["id"], text=message["content"]
                )
            for escalation_id in list(self._runner_asks):
                escalation = self._pending_escalations.get(escalation_id)
                if escalation is not None and escalation.resolved:
                    await self._answer_runner_escalation(escalation_id, escalation)
        await self._publish_events_immediately()

    def _record_runner_event(self, event: RunnerTurnEvent) -> None:
        iteration = self.state.current_iteration
        if event.kind == "message":
            self._events.add_event(
                EventTypes.LLM_CALL_COMPLETED,
                {
                    "role": "assistant",
                    "content": event.text or "",
                    "thinking": "",
                    "cost": "0",
                    "iteration": iteration,
                    # One turn of a CLI holds several replies; each is its own part.
                    "item_id": event.item_id,
                    "model_name": event.model or "runner",
                },
            )
        elif event.kind == "tool.call":
            self._runner_open_tools[event.item_id] = event.name
            self._events.add_event(
                EventTypes.TOOL_CALL_STARTED,
                {
                    "tool_name": event.name,
                    "tool_call_id": event.item_id,
                    "arguments": sanitize_tool_event_value(event.arguments),
                    "iteration": iteration,
                    "actor": self._runner_actor_data,
                },
            )
        else:
            self._runner_open_tools.pop(event.item_id, None)
            self._events.add_event(
                EventTypes.TOOL_CALL_COMPLETED,
                {
                    "tool_name": event.name,
                    "tool_call_id": event.item_id,
                    "result": event.output or "",
                    "success": bool(event.success),
                    "exit_code": event.exit_code,
                    "source": "runner",
                    "iteration": iteration,
                },
            )

    async def _close_open_runner_tools(self, reason: str) -> None:
        """Give each command the turn left running a result, so none stays open in the log."""
        if not self._runner_open_tools:
            return
        for item_id, name in self._runner_open_tools.items():
            self._events.add_event(
                EventTypes.TOOL_CALL_COMPLETED,
                {
                    "tool_name": name,
                    "tool_call_id": item_id,
                    "result": reason,
                    "success": False,
                    "source": "runner",
                    "iteration": self.state.current_iteration,
                },
            )
        self._runner_open_tools.clear()
        await self._publish_events_immediately()

    def _settle_steer(self, outcome: RunnerSteerOutcome) -> None:
        message = self._runner_steering.pop(outcome.message_id, None)
        if message is None:
            return
        if outcome.accepted:
            self.state.messages.append(Message(role="user", content=message["content"]))
        else:
            self._runner_held_back.append(message)

    async def _open_runner_escalation(self, ask: RunnerApprovalAsk) -> None:
        """The CLI waits for a person: an escalation of the run, as a tool's would be."""
        if ask.request_id in self._runner_seen_asks:
            return
        self._runner_seen_asks.add(ask.request_id)
        escalation_id = str(workflow.uuid4())
        escalation = PendingEscalation(
            escalation_id=escalation_id,
            tool_call_id=ask.item_id or ask.request_id,
            tool_name=ask.tool_name,
            tool_args=ask.arguments,
            approvers=approvers_for_tool(self.state.effective_policy, ask.tool_name),
        )
        self._pending_escalations[escalation_id] = escalation
        self._runner_asks[escalation_id] = ask.request_id
        self.state.status = ExecutionStatus.WAITING_FOR_APPROVAL
        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status="waiting_for_approval",
                workspace_id=self.state.workspace_id,
            )
        )
        self._events.add_event(
            EventTypes.HUMAN_APPROVAL_REQUESTED,
            {
                "escalation_id": escalation_id,
                "tool_name": ask.tool_name,
                "tool_call_id": escalation.tool_call_id,
                "iteration": self.state.current_iteration,
                "arguments": sanitize_tool_event_value(ask.arguments),
                "approvers": escalation.approvers,
                "actor": self._runner_actor_data,
                "message": f"The CLI asks to run '{ask.tool_name}'"
                + (f": {ask.reason}" if ask.reason else ""),
            },
        )

    async def _answer_runner_escalation(
        self, escalation_id: str, escalation: PendingEscalation
    ) -> None:
        request_id = self._runner_asks.pop(escalation_id)
        del self._pending_escalations[escalation_id]
        approved = bool(escalation.approved)
        self._events.add_event(
            EventTypes.HUMAN_APPROVAL_RECEIVED if approved else EventTypes.HUMAN_APPROVAL_DENIED,
            {
                "escalation_id": escalation_id,
                "tool_name": escalation.tool_name,
                "tool_call_id": escalation.tool_call_id,
                "iteration": self.state.current_iteration,
                "approved": approved,
                "approved_by": escalation.approved_by,
                "comment": escalation.comment,
            },
        )
        await self._deliver_to_runner(kind="decision", request_id=request_id, approved=approved)
        if not self._pending_escalations:
            self.state.status = ExecutionStatus.EXECUTING
            await self._persist_task_status(
                UpdateTaskStatusRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    status="running",
                    workspace_id=self.state.workspace_id,
                )
            )

    async def _expire_runner_escalations(self, reason: str) -> None:
        """Close the escalations of a turn that ended before anyone answered them."""
        if not self._runner_asks:
            return
        for escalation_id in list(self._runner_asks):
            self._runner_asks.pop(escalation_id)
            escalation = self._pending_escalations.pop(escalation_id, None)
            if escalation is None or escalation.resolved:
                continue
            self._events.add_event(
                EventTypes.HUMAN_APPROVAL_DENIED,
                {
                    "escalation_id": escalation_id,
                    "tool_name": escalation.tool_name,
                    "tool_call_id": escalation.tool_call_id,
                    "iteration": self.state.current_iteration,
                    "approved": False,
                    "approved_by": None,
                    "comment": reason,
                },
            )
        if not self._pending_escalations:
            self.state.status = ExecutionStatus.EXECUTING
            await self._persist_task_status(
                UpdateTaskStatusRequest(
                    user_context_data=self.state.user_context_data,
                    task_id=self.state.task_id,
                    status="running",
                    workspace_id=self.state.workspace_id,
                )
            )

    def _settle_runner_turn(self) -> None:
        """Messages the turn never took wait for the next one; its open questions are moot."""
        self._runner_held_back.extend(self._runner_steering.values())
        self._runner_steering.clear()
        self._message_queue[:0] = self._runner_held_back
        self._runner_held_back = []

    def _complete_runner_turn(self, response: str) -> None:
        self.state.success = True
        self.state.final_response = response
        self.state.status = ExecutionStatus.COMPLETED
        self.state.failure_reason = None
        self.state.error_message = None
        self._awaiting_input = True
        self._completed_status = UpdateTaskStatusRequest(
            user_context_data=self.state.user_context_data,
            task_id=self.state.task_id,
            status="completed",
            result=json.dumps({"response": response}, ensure_ascii=False),
            workspace_id=self.state.workspace_id,
        )
        window = self._follow_up_window()
        if window is None:
            self._awaiting_input = False
            return
        self._events.add_event(
            EventTypes.WORKFLOW_AWAITING_FOLLOW_UP,
            {
                "state": "awaiting_follow_up",
                "timeout_seconds": int(window.total_seconds()),
                **({"final_response": response} if self._interaction_contract_enabled else {}),
            },
        )

    @property
    def _runner_actor_data(self) -> dict[str, str] | None:
        return self._runner_actor.model_dump() if self._runner_actor else None

    async def _deliver_to_runner(self, **fields: Any) -> None:
        await workflow.execute_activity(
            Activities.DELIVER_TO_RUNNER,
            DeliverToRunnerRequest(
                client_id=str(self._runner_client_id),
                task_id=self.state.task_id,
                turn_key=str(self._runner_turn_key),
                **fields,
            ),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=bookkeeping_retry_policy(),
        )
