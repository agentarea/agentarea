"""Batch windows of stream triggers (ADR-0040 §4): who holds a batch, and what its task gets.

A trigger with a window does not fire per event. Each admitted event joins the
open batch of its trigger, one Temporal workflow per batch (see
``trigger_batch_workflow``), and its reaction is recorded as ``batched`` with
that workflow's id. Events a messenger admitted carry their sender's authority,
so each admitted sender has a batch of their own. When the batch fires, its
task is told every event the way a single event is told (``render_event_block``),
under ``events``.
"""

from datetime import UTC
from typing import Any, Protocol
from uuid import UUID, uuid5

from agentarea_common.workflow.executor import WorkflowConfig, WorkflowExecutor
from agentarea_execution.workflows.trigger_batch_workflow import (
    ADD_EVENT_SIGNAL,
    TRIGGER_BATCH_WORKFLOW,
    BatchSpec,
)
from agentarea_streams.domain import StreamEvent

from .event_context import TriggerEvent

_BATCH_NAMESPACE = UUID("3c9e2b71-5d84-4f0a-b6e3-8a1f2c7d9e45")


def batch_workflow_id(trigger_id: UUID, caller: str | None) -> str:
    """The workflow holding the open batch of a trigger, or of one admitted sender of it."""
    if caller is None:
        return f"trigger-batch-{trigger_id}"
    return f"trigger-batch-{trigger_id}-{uuid5(_BATCH_NAMESPACE, caller)}"


def batch_task_id(subscription_id: UUID, first_event_id: UUID) -> UUID:
    """The task a batch starts; an event is in one batch only, so its first event names it."""
    return uuid5(_BATCH_NAMESPACE, f"{subscription_id}:batch:{first_event_id}")


def batch_event(event: StreamEvent, body: Any) -> dict[str, Any]:
    """One event of a batch: what a single firing tells beside its data, then the data."""
    received_at = event.received_at
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)
    data = dict(event.data)
    if body is not None:
        data["body"] = body
    return {
        "id": str(event.id),
        "kind": event.type,
        "key": event.event_key,
        "received_at": received_at.astimezone(UTC).isoformat(),
        "data": data,
    }


def batch_trigger_event(events: list[dict[str, Any]], *, stream_name: str) -> TriggerEvent:
    return TriggerEvent(stream_name=stream_name, data={"events": events})


class TriggerBatches(Protocol):
    async def add(self, spec: BatchSpec, event_id: UUID, *, workflow_id: str) -> None:
        """Hand the event to the open batch ``workflow_id``, opening one with ``spec``."""
        ...


class TemporalTriggerBatches:
    """Signal-with-start on the batch workflow: a closed batch's id opens the next one."""

    def __init__(self, executor: WorkflowExecutor, *, task_queue: str):
        self._executor = executor
        self._task_queue = task_queue

    async def add(self, spec: BatchSpec, event_id: UUID, *, workflow_id: str) -> None:
        await self._executor.start_workflow(
            TRIGGER_BATCH_WORKFLOW,
            workflow_id,
            spec.model_dump(mode="json"),
            WorkflowConfig(
                task_queue=self._task_queue,
                start_signal=ADD_EVENT_SIGNAL,
                start_signal_args=[str(event_id)],
                # A failed run would restart without the events signalled into it.
                retry_attempts=1,
            ),
        )
