"""The one writer of a run's record: the task log, then its events on the broker."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_common.events.contract import LIVE_ONLY_TYPES
from agentarea_common.events.task_stream import broadcast_live, publish_task_event, task_event
from agentarea_common.utils.pg_text import pg_storable
from agentarea_tasks.domain.feed import FeedBodies, feed_event
from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.task_log import TaskLog
from sqlalchemy.exc import DataError, IntegrityError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ...interfaces import ActivityDependencies
from ...models import LogRow, RecordRequest, RecordResult
from .events import ledger_lines, store_task_events
from .task_state import task_outcome
from .tool_audit import audit_line, tool_audit_entry

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def log_entry(row: LogRow, execution_id: str | None) -> ConversationEntry:
    """A row the workflow sent, as the task log stores it."""
    return ConversationEntry(
        seq=row.seq,
        event_id=UUID(row.event_id),
        kind=row.kind,
        role=row.role,
        content=row.content,
        tool_calls=row.tool_calls,
        tool_call_id=row.tool_call_id,
        name=row.name,
        attachments=row.attachments,
        meta=row.meta,
        iteration=row.iteration,
        execution_id=execution_id,
        occurred_at=datetime.fromisoformat(row.timestamp) if row.timestamp else None,
    )


def row_event(row: LogRow) -> dict[str, Any] | None:
    """An event row as the workflow event it records; None for any other row."""
    if row.kind != "event":
        return None
    return {
        "event_type": row.name,
        "event_id": row.event_id,
        "timestamp": row.timestamp or datetime.now(UTC).isoformat(),
        "data": row.meta or {},
    }


def make_record_activities(
    dependencies: ActivityDependencies, container: ActivityServiceContainer
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    async def record_activity(request: RecordRequest) -> RecordResult:
        """Append the run's log rows, then publish its events.

        One transaction writes the rows, the task's status and result, the spend
        lines and the audit rows the events stand for. Each event row and each
        message a person sent is then published once to ``tasks.events``; who
        reads it (delivery, the live feed) is not the run's business. Live-only
        signals are broadcast and kept nowhere. Every step is keyed by the
        workflow's ids, so Temporal retrying the whole call writes nothing twice
        and never calls a model again. Content Postgres cannot store is made
        storable before the transaction, and a row the database still refuses
        fails the call for good: retrying would refuse it again and hold the run.
        """
        user_context = create_user_context(
            {
                "user_id": request.user_id,
                "workspace_id": request.workspace_id,
                "agent_id": request.agent_id,
            }
        )
        try:
            sent = [json.loads(event_json) for event_json in request.events_json]
            live = [event for event in sent if event["event_type"] in LIVE_ONLY_TYPES]
            # A run from before event rows sends its stored events here.
            legacy = [event for event in sent if event["event_type"] not in LIVE_ONLY_TYPES]
            stored = [
                event for row in request.rows if (event := row_event(row)) is not None
            ] + legacy
            stored = pg_storable(stored)
            audits = [
                audit_line(UUID(event["event_id"]), entry, requested_by=request.user_id)
                for event in stored
                if (entry := tool_audit_entry(event)) is not None
            ]
            entries = [log_entry(row, request.execution_id) for row in request.rows]
            async with ActivityContext(container, user_context) as ctx:
                session = container._database.async_session_factory()
                ctx._sessions.append(session)
                try:
                    await TaskLog(session, user_context, container.log_body_store()).append(
                        UUID(request.task_id),
                        entries,
                        execution_id=request.execution_id,
                        outcome=task_outcome(request.status) if request.status else None,
                        costs=ledger_lines(
                            stored, workspace_id=request.workspace_id, user_id=request.user_id
                        ),
                        audits=audits,
                    )
                except LookupError as gone:
                    # A deleted task stays deleted: retrying would only hold the run.
                    raise ApplicationError(
                        str(gone), type="TaskNotFound", non_retryable=True
                    ) from gone
                except (DataError, IntegrityError) as refused:
                    raise ApplicationError(
                        f"the task log refused the run's record: {refused.orig}",
                        type="TaskLogRejected",
                        non_retryable=True,
                    ) from refused
            if stored:
                # Kept only for the enterprise usage emitter, which reads
                # llm.call.completed from the old task_events table.
                async with ActivityContext(container, user_context) as ctx:
                    await store_task_events(
                        ctx, stored, workspace_id=request.workspace_id, user_id=request.user_id
                    )
            await _publish(request, entries, legacy, live)
        except Exception:
            logger.error(
                "Failed to record %d rows and %d events of task %s",
                len(request.rows),
                len(request.events_json),
                request.task_id,
                exc_info=True,
            )
            raise
        return RecordResult(rows=len(request.rows), events=len(request.events_json))

    async def _publish(
        request: RecordRequest,
        entries: list[ConversationEntry],
        legacy: list[dict[str, Any]],
        live: list[dict[str, Any]],
    ) -> None:
        broker = dependencies.broker_client
        if broker is None:
            raise RuntimeError(
                "the record activity publishes task events; it needs a broker client"
            )
        bodies = FeedBodies.of(entries)
        for entry in entries:
            shown = feed_event(entry, bodies)
            if shown is None or entry.event_id is None:
                continue
            event_type, data = shown
            await publish_task_event(
                broker,
                task_event(
                    task_id=request.task_id,
                    workspace_id=request.workspace_id,
                    event_type=event_type,
                    event_id=str(entry.event_id),
                    timestamp=entry.occurred_at or datetime.now(UTC),
                    data=pg_storable(data),
                    seq=entry.seq,
                ),
            )
        for event in legacy:
            await publish_task_event(broker, _event_envelope(request, event))
        for event in live:
            await broadcast_live(broker, _event_envelope(request, event))

    def _event_envelope(request: RecordRequest, event: dict[str, Any]) -> Any:
        return task_event(
            task_id=request.task_id,
            workspace_id=request.workspace_id,
            event_type=event["event_type"],
            event_id=event["event_id"],
            timestamp=datetime.fromisoformat(event["timestamp"]),
            data=event["data"],
        )

    return [record_activity]
