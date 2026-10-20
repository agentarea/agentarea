"""Riding out an outage of a service the run needs, instead of failing on it."""

import asyncio
from datetime import datetime, timedelta
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

# The wait of runs whose config recorded none. Never change it: those runs
# replay with these timers.
LEGACY_OUTAGE_WAIT = OutageWait(
    retry_window=timedelta(minutes=5),
    backoff=[timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=10)],
    deadline=timedelta(hours=24),
)
OUTAGE_INITIAL_INTERVAL = timedelta(seconds=2)
OUTAGE_MAX_INTERVAL = timedelta(seconds=60)
# While the run waits, each try is short: the wait itself is the backoff.
OUTAGE_TRY_ATTEMPTS = 3
# The last try, at the deadline, still gets this long.
OUTAGE_LAST_TRY = timedelta(minutes=1)
# Room left before the run's own execution timeout to record its failure.
OUTAGE_FINALIZE_MARGIN = timedelta(minutes=10)


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


def _application_cause(error: BaseException) -> BaseException:
    cause = error
    while cause.__cause__ is not None and not isinstance(cause, ApplicationError):
        cause = cause.__cause__
    return cause


def failure_text(error: BaseException) -> str:
    """What the activity itself said, under Temporal's wrapping (a timeout keeps the last failure)."""
    cause = _application_cause(error)
    return cause.message if isinstance(cause, ApplicationError) else str(cause)


def outage_service(error: BaseException) -> str:
    """The service the activity named as unreachable."""
    cause = _application_cause(error)
    if isinstance(cause, ApplicationError):
        for detail in cause.details or ():
            if isinstance(detail, dict) and isinstance(detail.get("service"), str):
                return detail["service"]
    return "A service"


def _span(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    if seconds % 3600 == 0:
        return f"{seconds // 3600} h"
    if seconds % 60 == 0:
        return f"{seconds // 60} min"
    return f"{seconds} s"


class OutageWaitMixin(AgentWorkflowBase):
    """One way for an activity to outlast an outage of what it calls.

    The activity retries with backoff for the run's retry window. If it still
    fails on a retryable error, the run says it is waiting for the service,
    retries on a capped backoff, and goes on by itself when the service
    answers, with a result or with a final error. A resume retries at once (and
    lifts a pause); a pause holds the retries; a stop ends the wait. The run
    fails with ``DependencyUnavailable`` at the deadline, or before its own
    execution timeout would end it unrecorded. A final failure (refused, gone)
    reaches the caller unchanged.
    """

    def _outage_wait(self) -> OutageWait:
        recorded = self.state.agent_config.get("outage_wait")
        return OutageWait.model_validate(recorded) if recorded else LEGACY_OUTAGE_WAIT

    def _outage_give_up_at(self, since: datetime, wait: OutageWait) -> datetime:
        give_up_at = since + wait.deadline
        info = workflow.info()
        if info.execution_timeout:
            end = info.workflow_start_time + info.execution_timeout
            give_up_at = min(give_up_at, end - OUTAGE_FINALIZE_MARGIN)
        if info.run_timeout:
            give_up_at = min(
                give_up_at, info.start_time + info.run_timeout - OUTAGE_FINALIZE_MARGIN
            )
        return give_up_at

    async def _execute_through_outage(
        self,
        activity: str,
        request: Any,
        result_type: type[T],
        *,
        what: str,
        heartbeat_timeout: timedelta | None = None,
    ) -> T:
        """Run ``activity``, waiting out an outage; ``what`` says what the run is doing."""
        try:
            result = await self._retry_through_outage(
                activity, request, result_type, what, heartbeat_timeout
            )
        except BaseException as error:
            if self._waiting_for_outage:
                stopped = isinstance(error, asyncio.CancelledError) or self._is_cancellation(error)
                gave_up = (
                    isinstance(error, ApplicationError) and error.type == DEPENDENCY_UNAVAILABLE
                )
                waited = workflow.now() - (self._outage_since or workflow.now())
                service = self._outage_service or "A service"
                self._clear_outage_wait()
                if not stopped and not gave_up:
                    await self._leave_outage_wait(service, waited, error=failure_text(error))
            raise
        if self._waiting_for_outage:
            waited = workflow.now() - (self._outage_since or workflow.now())
            service = self._outage_service or "A service"
            self._clear_outage_wait()
            await self._leave_outage_wait(service, waited)
        return result

    async def _retry_through_outage(
        self,
        activity: str,
        request: Any,
        result_type: type[T],
        what: str,
        heartbeat_timeout: timedelta | None,
    ) -> T:
        wait = self._outage_wait()
        extra: dict[str, Any] = (
            {"heartbeat_timeout": heartbeat_timeout} if heartbeat_timeout else {}
        )
        try_timeout = min(ACTIVITY_TIMEOUT, wait.retry_window)
        options: dict[str, Any] = {
            "schedule_to_close_timeout": wait.retry_window,
            "retry_policy": outage_policy(),
        }
        give_up_at: datetime | None = None
        tries = 0
        while True:
            # Cleared before the try, so a resume during it retries right after.
            self._retry_outage_now = False
            try:
                return await workflow.execute_activity(
                    activity,
                    args=[request],
                    result_type=result_type,
                    start_to_close_timeout=try_timeout,
                    **extra,
                    **options,
                )
            except ActivityError as error:
                if self._is_cancellation(error) or not is_outage(error):
                    raise
                reason = failure_text(error)
                now = workflow.now()
                if give_up_at is None:
                    give_up_at = self._outage_give_up_at(now, wait)
                    await self._enter_outage_wait(outage_service(error), what, reason, wait)
                if now >= give_up_at:
                    raise self._gave_up(what, reason, give_up_at) from error
            delay = min(wait.backoff[min(tries, len(wait.backoff) - 1)], give_up_at - now)
            tries += 1
            await self._hold_between_tries(delay)
            now = workflow.now()
            if now > give_up_at:
                raise self._gave_up(what, reason, give_up_at)
            window = max(give_up_at - now, OUTAGE_LAST_TRY)
            try_timeout = min(ACTIVITY_TIMEOUT, wait.retry_window, window)
            options = {
                "schedule_to_close_timeout": window,
                "retry_policy": make_retry_policy(OUTAGE_TRY_ATTEMPTS),
            }

    def _gave_up(self, what: str, reason: str, give_up_at: datetime) -> ApplicationError:
        waited = give_up_at - (self._outage_since or give_up_at)
        service = self._outage_service or "A service"
        return ApplicationError(
            f"{service} stayed unreachable for {_span(waited)} while {what}: {reason}",
            type=DEPENDENCY_UNAVAILABLE,
            non_retryable=True,
        )

    async def _hold_between_tries(self, delay: timedelta) -> None:
        """Sleep ``delay``, or less on a resume; never retry while the run is paused."""
        try:
            await workflow.wait_condition(
                lambda: self._retry_outage_now and not self._paused, timeout=delay
            )
        except TimeoutError:
            pass
        if self._paused:
            await workflow.wait_condition(lambda: not self._paused)

    def _clear_outage_wait(self) -> None:
        self._waiting_for_outage = False
        self._outage_reason = None
        self._outage_service = None
        self._outage_since = None
        self._retry_outage_now = False

    async def _enter_outage_wait(
        self, service: str, what: str, reason: str, wait: OutageWait
    ) -> None:
        self._waiting_for_outage = True
        self._outage_service = service
        self._outage_since = workflow.now()
        self._outage_reason = (
            f"{service} is unreachable while {what}; the run retries on its own: {reason}"
        )
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

    async def _leave_outage_wait(
        self, service: str, waited: timedelta, *, error: str | None = None
    ) -> None:
        """The service answered: with the result, or with a final ``error`` the caller handles."""
        self.state.status = ExecutionStatus.EXECUTING
        self._events.add_event(
            EventTypes.WORKFLOW_INFRASTRUCTURE_RECOVERED,
            {
                "service": service,
                "waited_seconds": int(waited.total_seconds()),
                **({"error": error} if error else {}),
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
