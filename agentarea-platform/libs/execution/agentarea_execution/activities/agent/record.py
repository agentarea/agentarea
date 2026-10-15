"""The one writer of a run's record: the task log, then its events."""

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_tasks.domain.models import ConversationEntry
from agentarea_tasks.infrastructure.task_log import TaskLog
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ...interfaces import ActivityDependencies
from ...models import LogRow, RecordRequest, RecordResult
from .events import fan_out, ledger_lines, store_task_events
from .task_state import task_outcome
from .tool_audit import audit_line, tool_audit_entry

if TYPE_CHECKING:
    from ..dependencies import ActivityServiceContainer

logger = logging.getLogger(__name__)


def log_entry(row: LogRow) -> ConversationEntry:
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
    )


def make_record_activities(
    dependencies: ActivityDependencies, container: "ActivityServiceContainer"
) -> list[Callable[..., Any]]:
    from ..dependencies import ActivityContext, create_user_context

    @activity.defn
    async def record_activity(request: RecordRequest) -> RecordResult:
        """Append the run's log rows, then publish its events.

        One transaction writes the rows, the task's status and result, the spend
        lines and the audit rows the events stand for. The events are then
        stored in ``task_events`` and sent to the live stream and the task's
        channels. Every step is keyed by the workflow's ids, so Temporal retrying
        the whole call writes nothing twice and never calls a model again.
        """
        user_context = create_user_context(
            {"user_id": request.user_id, "workspace_id": request.workspace_id}
        )
        try:
            events = [json.loads(event_json) for event_json in request.events_json]
            audits = [
                audit_line(UUID(event["event_id"]), entry, requested_by=request.user_id)
                for event in events
                if (entry := tool_audit_entry(event)) is not None
            ]
            async with ActivityContext(container, user_context) as ctx:
                session = container._database.async_session_factory()
                ctx._sessions.append(session)
                try:
                    await TaskLog(session, user_context, container.log_body_store()).append(
                        UUID(request.task_id),
                        [log_entry(row) for row in request.rows],
                        execution_id=request.execution_id,
                        outcome=task_outcome(request.status) if request.status else None,
                        costs=ledger_lines(
                            events, workspace_id=request.workspace_id, user_id=request.user_id
                        ),
                        audits=audits,
                    )
                except LookupError as gone:
                    # A deleted task stays deleted: retrying would only hold the run.
                    raise ApplicationError(
                        str(gone), type="TaskNotFound", non_retryable=True
                    ) from gone
            if events:
                async with ActivityContext(container, user_context) as ctx:
                    stored_events = await store_task_events(
                        ctx, events, workspace_id=request.workspace_id, user_id=request.user_id
                    )
                await fan_out(dependencies, container, user_context, events, stored_events)
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

    return [record_activity]
