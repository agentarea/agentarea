"""Riding out an outage of a service the run needs, instead of failing on it."""

from datetime import timedelta
from typing import Any, TypeVar

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, RetryState

from ...models import OutageWait, UpdateTaskStatusRequest
from ..constants import ACTIVITY_TIMEOUT, EventTypes, ExecutionStatus
from ..retry import make_retry_policy
from .base import AgentWorkflowBase

T = TypeVar("T")

# What a run that waited too long fails with; its message is shown as it is.
DEPENDENCY_UNAVAILABLE = "DependencyUnavailable"

OUTAGE_INITIAL_INTERVAL = timedelta(seconds=2)
OUTAGE_MAX_INTERVAL = timedelta(seconds=60)
# While the run waits, each try is short: the wait itself is the backoff.
OUTAGE_TRY_ATTEMPTS = 3


def outage_policy() -> RetryPolicy:
    """The first phase: retry with backoff until the window (schedule_to_close) ends."""
    return make_retry_policy(
        0, initial_interval=OUTAGE_INITIAL_INTERVAL, maximum_interval=OUTAGE_MAX_INTERVAL
    )


def is_outage(error: BaseException) -> bool:
    """Whether an activity gave up on a retryable failure: its retries ran out, not its case."""
    return isinstance(error, ActivityError) and error.retry_state in (
        RetryState.TIMEOUT,
        RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )


def failure_text(error: BaseException) -> str:
    """What the activity itself said, under Temporal's wrapping (a timeout keeps the last failure)."""
    cause = error
    while cause.__cause__ is not None and not isinstance(cause, ApplicationError):
        cause = cause.__cause__
    return cause.message if isinstance(cause, ApplicationError) else str(cause)


class OutageWaitMixin(AgentWorkflowBase):
    """One way for an activity to outlast an outage of what it calls.

    The activity retries with backoff for the run's retry window. If it still
    fails on a retryable error, the run says it is waiting for a service, then
    retries on a capped backoff for as long as the deadline allows, and goes on
    by itself when the service answers. A resume retries at once; a stop stops
    the wait. Past the deadline the run fails with a ``DependencyUnavailable``
    error. A final failure (refused, gone) is raised to the caller unchanged.
    """

    def _outage_wait(self) -> OutageWait:
        return OutageWait.model_validate(self.state.agent_config.get("outage_wait") or {})

    async def _execute_through_outage(
        self, activity: str, request: Any, result_type: type[T], *, service: str
    ) -> T:
        wait = self._outage_wait()
        try_timeout = min(ACTIVITY_TIMEOUT, wait.retry_window)
        options: dict[str, Any] = {
            "schedule_to_close_timeout": wait.retry_window,
            "retry_policy": outage_policy(),
        }
        waiting_since = None
        tries = 0
        while True:
            try:
                result = await workflow.execute_activity(
                    activity,
                    args=[request],
                    result_type=result_type,
                    start_to_close_timeout=try_timeout,
                    **options,
                )
            except ActivityError as error:
                if self._is_cancellation(error) or not is_outage(error):
                    raise
                reason = failure_text(error)
                now = workflow.now()
                if waiting_since is None:
                    waiting_since = now
                    await self._enter_outage_wait(service, reason, wait)
                if now - waiting_since >= wait.deadline:
                    self._waiting_for_outage = False
                    raise ApplicationError(
                        f"{service} stayed unavailable for {wait.deadline}: {reason}",
                        type=DEPENDENCY_UNAVAILABLE,
                        non_retryable=True,
                    ) from error
                delay = min(
                    wait.backoff[min(tries, len(wait.backoff) - 1)],
                    waiting_since + wait.deadline - now,
                )
                tries += 1
                options = {"retry_policy": make_retry_policy(OUTAGE_TRY_ATTEMPTS)}
                self._retry_outage_now = False
                try:
                    await workflow.wait_condition(lambda: self._retry_outage_now, timeout=delay)
                except TimeoutError:
                    pass
                continue
            if waiting_since is not None:
                await self._leave_outage_wait(service, workflow.now() - waiting_since)
            return result

    async def _enter_outage_wait(self, service: str, reason: str, wait: OutageWait) -> None:
        self._waiting_for_outage = True
        self._outage_reason = f"{service} is unavailable: {reason}"
        self.state.status = ExecutionStatus.WAITING_FOR_INFRASTRUCTURE
        self._events.add_event(
            EventTypes.WORKFLOW_AWAITING_INFRASTRUCTURE,
            {
                "service": service,
                "reason": reason,
                "message": self._outage_reason,
                "retry_in_seconds": int(wait.backoff[0].total_seconds()),
                "deadline_seconds": int(wait.deadline.total_seconds()),
                "iteration": self.state.current_iteration,
            },
        )
        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status=ExecutionStatus.WAITING_FOR_INFRASTRUCTURE,
                error_message=self._outage_reason,
                workspace_id=self.state.workspace_id,
            )
        )
        await self._publish_events_immediately()

    async def _leave_outage_wait(self, service: str, waited: timedelta) -> None:
        self._waiting_for_outage = False
        self._outage_reason = None
        self.state.status = ExecutionStatus.EXECUTING
        self._events.add_event(
            EventTypes.WORKFLOW_INFRASTRUCTURE_RECOVERED,
            {
                "service": service,
                "waited_seconds": int(waited.total_seconds()),
                "iteration": self.state.current_iteration,
            },
        )
        await self._persist_task_status(
            UpdateTaskStatusRequest(
                user_context_data=self.state.user_context_data,
                task_id=self.state.task_id,
                status="running",
                workspace_id=self.state.workspace_id,
            )
        )
        await self._publish_events_immediately()
