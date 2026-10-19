"""One open batch of a windowed stream trigger (ADR-0040 §4): one timer, one firing.

The router hands every admitted event to the batch of its trigger by
signal-with-start, so the first event opens the batch and later ones join it.
The workflow holds event ids only, and each id once: a redelivered event joins
nothing. When the window has passed or the batch is full, it fires the trigger
once with every event in it. Events that arrive while it fires open the next
batch in a new run, so a run's history stays bounded by the batch's size.

Cancelled, the batch closes: its events are recorded as skipped and no task
starts.
"""

import asyncio
from datetime import timedelta
from uuid import UUID

from pydantic import BaseModel, Field
from temporalio import workflow
from temporalio.common import RetryPolicy

TRIGGER_BATCH_WORKFLOW = "TriggerBatchWorkflow"
ADD_EVENT_SIGNAL = "add_event"
FIRE_TRIGGER_BATCH = "fire_trigger_batch_activity"
CLOSE_TRIGGER_BATCH = "close_trigger_batch_activity"
CANCELLED_REASON = "the batch was cancelled before it fired"

_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)


class BatchSpec(BaseModel):
    """What a batch fires and when; fixed for the run that holds it."""

    trigger_id: UUID
    subscription_id: UUID
    workspace_id: str
    configured_by: str = Field(description="Whose context the subscription reacts in.")
    caller: str | None = Field(
        default=None, description="The admitted sender every event of this batch came from."
    )
    window_seconds: float | None = Field(default=None, gt=0)
    max_events: int = Field(ge=1)
    pending: list[UUID] = Field(
        default_factory=list, description="Events carried over from the previous run."
    )


class OpenBatch(BaseModel):
    """The events of one batch, as its activities get them."""

    spec: BatchSpec
    workflow_id: str
    event_ids: list[UUID]
    reason: str | None = None


@workflow.defn(name=TRIGGER_BATCH_WORKFLOW)
class TriggerBatchWorkflow:
    def __init__(self) -> None:
        self._pending: list[UUID] = []
        self._seen: set[UUID] = set()

    @workflow.signal(name=ADD_EVENT_SIGNAL)
    def add_event(self, event_id: UUID) -> None:
        if event_id in self._seen:
            return
        self._seen.add(event_id)
        self._pending.append(event_id)

    @workflow.run
    async def run(self, spec: BatchSpec) -> int:
        signalled = [e for e in self._pending if e not in spec.pending]
        self._pending = list(dict.fromkeys(spec.pending))
        self._seen = set(self._pending)
        for event_id in signalled:
            self.add_event(event_id)
        workflow_id = workflow.info().workflow_id
        try:
            await workflow.wait_condition(lambda: bool(self._pending))
            try:
                await workflow.wait_condition(
                    lambda: len(self._pending) >= spec.max_events,
                    timeout=(
                        timedelta(seconds=spec.window_seconds)
                        if spec.window_seconds is not None
                        else None
                    ),
                )
            except TimeoutError:
                pass
            batch = self._pending[: spec.max_events]
            await workflow.execute_activity(
                FIRE_TRIGGER_BATCH,
                OpenBatch(spec=spec, workflow_id=workflow_id, event_ids=batch),
                result_type=int,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_ACTIVITY_RETRY,
            )
        except asyncio.CancelledError:
            await workflow.execute_activity(
                CLOSE_TRIGGER_BATCH,
                OpenBatch(
                    spec=spec,
                    workflow_id=workflow_id,
                    event_ids=self._pending,
                    reason=CANCELLED_REASON,
                ),
                result_type=int,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=_ACTIVITY_RETRY,
            )
            return 0
        rest = self._pending[len(batch) :]
        if rest:
            workflow.continue_as_new(spec.model_copy(update={"pending": rest}))
        return len(batch)
