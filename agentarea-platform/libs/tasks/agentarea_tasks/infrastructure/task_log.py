"""A task's log, written through one door and read as the model's window.

``TaskLog.append`` is the only writer of a run's record: the log rows and, in
the caller's transaction, the task's outcome, its spend lines and its audit
rows. Every row carries the workflow's ``event_id``, so a retried append writes
nothing twice. A body larger than ``BODY_OFFLOAD_BYTES`` is stored outside the
row, which keeps only its reference.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from agentarea_common.audit import AuditService
from agentarea_common.auth.context import UserContext
from agentarea_common.events.contract import MESSAGE_RECEIVED, TOOL_CALL, TOOL_RESULT
from agentarea_common.utils.pg_text import pg_storable
from sqlalchemy import ColumnElement, and_, func, null, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.costs import CostEntry
from ..domain.feed import FeedBodies
from ..domain.models import ConversationEntry
from .cost_repository import CostEntryRepository
from .orm import TaskConversationEntryORM, TaskORM
from .repository import TaskRepository, entry_from_row

# A row body above this many UTF-8 bytes is stored by reference.
BODY_OFFLOAD_BYTES = 64 * 1024

WINDOW_KINDS = ("message", "compaction")
# A row whose tool calls are stored by reference names the reference in its meta.
TOOL_CALLS_PART = "tool_calls"
TOOL_CALLS_REF = "tool_calls_ref"

# A task that runs or completes again no longer carries an earlier run's failure.
ERROR_CLEARING_STATUSES = frozenset({"running", "completed"})


def _jsonb(value: Any) -> Any:
    """A JSONB column's value: SQL NULL for none, never the JSON ``null``."""
    return null() if value is None else pg_storable(value)


class LogBodyStore(Protocol):
    """Where bodies too large for a log row live; deleted with the task's stored context."""

    async def put(
        self, workspace_id: str, task_id: UUID, event_id: UUID, body: str, *, part: str = "content"
    ) -> str:
        """Store one part of a row's body (its ``content``, its ``tool_calls``); its reference."""
        ...

    async def get(self, ref: str) -> str:
        """The body stored under ``ref``."""
        ...


@dataclass(frozen=True)
class TaskOutcome:
    """What a run sets on its task row: status, and optionally result, error and metadata.

    ``metadata_patch`` is merged into the task's metadata, leaving other keys alone.
    """

    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    metadata_patch: dict[str, Any] | None = None

    def error_fields(self) -> dict[str, Any]:
        """The ``error`` this outcome writes: its own, or cleared once the task runs again.

        A failed or stopped run's later update without an error keeps the one it set.
        """
        if self.error is not None:
            return {"error": self.error}
        if self.status in ERROR_CLEARING_STATUSES:
            return {"error": None}
        return {}


@dataclass(frozen=True)
class AuditLine:
    """One audit row a run's record stands for, stored once under its event's id."""

    event_id: UUID
    action: str
    task_id: str | None
    actor_type: str
    actor_id: str
    event_metadata: dict[str, Any] = field(default_factory=dict)


def answered_messages(entries: Sequence[ConversationEntry]) -> list[ConversationEntry]:
    """The entries a chat model accepts in order.

    A tool result is valid only as the answer to a call of the assistant turn
    right before it, and every call of that turn needs its answer before the
    next message. A turn whose calls are not all answered is dropped with its
    partial answers, and so is a tool result no call asked for.
    """
    valid: list[ConversationEntry] = []
    open_calls: set[str] = set()
    turn_start = 0
    for entry in entries:
        if entry.role == "tool":
            if entry.tool_call_id in open_calls:
                valid.append(entry)
                open_calls.discard(entry.tool_call_id)
            continue
        if open_calls:
            del valid[turn_start:]
            open_calls = set()
        if entry.role == "assistant" and entry.tool_calls:
            call_ids = [call.get("id") for call in entry.tool_calls]
            if not all(isinstance(call_id, str) and call_id for call_id in call_ids):
                continue
            open_calls = {call_id for call_id in call_ids if isinstance(call_id, str)}
            turn_start = len(valid)
        valid.append(entry)
    if open_calls:
        del valid[turn_start:]
    return valid


def model_window(entries: Sequence[ConversationEntry]) -> list[ConversationEntry]:
    """The window the model sees: the system prompt, the latest compaction, the messages after.

    The system prompt is the log's first system message (row 0 of every run
    that wrote one). Event rows never enter the window.
    """
    ordered = sorted(
        (entry for entry in entries if entry.kind in WINDOW_KINDS), key=lambda e: e.seq
    )
    system = next(
        (entry for entry in ordered if entry.kind == "message" and entry.role == "system"), None
    )
    compaction = next((entry for entry in reversed(ordered) if entry.kind == "compaction"), None)
    start = compaction.seq if compaction is not None else -1
    rest = [
        entry
        for entry in ordered
        if entry.kind == "message"
        and entry.seq > start
        and (system is None or entry.seq != system.seq)
    ]
    head = [entry for entry in (system, compaction) if entry is not None]
    return [*head, *answered_messages(rest)]


class TaskLog:
    """One task log in one workspace, on the caller's session (and transaction)."""

    def __init__(self, session: AsyncSession, user_context: UserContext, bodies: LogBodyStore):
        self.session = session
        self.user_context = user_context
        self.bodies = bodies

    async def append(
        self,
        task_id: UUID,
        rows: Sequence[ConversationEntry],
        *,
        execution_id: str | None = None,
        outcome: TaskOutcome | None = None,
        costs: Sequence[CostEntry] = (),
        audits: Sequence[AuditLine] = (),
    ) -> None:
        """Write the rows, the outcome, the spend lines and the audit rows; each once.

        The rows carry the task's ``correlation_id`` and ``causation_id``.
        """
        task = (
            await self.session.execute(
                select(
                    TaskORM.id,
                    TaskORM.correlation_id,
                    TaskORM.causation_id,
                    TaskORM.task_metadata,
                ).where(
                    TaskORM.id == task_id, TaskORM.workspace_id == self.user_context.workspace_id
                )
            )
        ).one_or_none()
        if task is None:
            raise LookupError(f"task {task_id} not found in workspace")
        if rows:
            await self._insert(task, rows, execution_id)
        if outcome is not None:
            await self._set_outcome(task, outcome)
        if costs:
            await CostEntryRepository(self.session, self.user_context).record(costs)
        if audits:
            audit = AuditService(self.session, self.user_context)
            for line in audits:
                await audit.record_once(
                    line.event_id,
                    line.action,
                    "task",
                    line.task_id,
                    actor_type=line.actor_type,
                    actor_id=line.actor_id,
                    event_metadata=pg_storable(line.event_metadata),
                )
        await self.session.flush()

    async def window(self, task_id: UUID, end_seq: int) -> list[ConversationEntry]:
        """The model's window over the rows before ``end_seq``, read in one query."""
        entries = TaskConversationEntryORM
        scope = and_(
            entries.task_id == task_id,
            entries.workspace_id == self.user_context.workspace_id,
            entries.seq < end_seq,
        )
        latest_compaction = (
            select(func.max(entries.seq)).where(scope, entries.kind == "compaction")
        ).scalar_subquery()
        first_system = (
            select(func.min(entries.seq)).where(
                scope, entries.kind == "message", entries.role == "system"
            )
        ).scalar_subquery()
        result = await self.session.execute(
            select(entries)
            .where(
                scope,
                entries.kind.in_(WINDOW_KINDS),
                or_(
                    entries.seq >= func.coalesce(latest_compaction, 0),
                    entries.seq == first_system,
                ),
            )
            .order_by(entries.seq)
        )
        # Resolved first: pairing a tool result with its call needs the calls.
        rows = [await self._resolved(entry_from_row(row)) for row in result.scalars().all()]
        return model_window(rows)

    async def _insert(
        self, task: Row[Any], rows: Sequence[ConversationEntry], execution_id: str | None
    ) -> None:
        values = []
        for row in rows:
            if row.event_id is None:
                raise ValueError(f"log row {row.seq} of task {task.id} has no event_id")
            content, body_ref = pg_storable(row.content), row.body_ref
            if len(content.encode("utf-8")) > BODY_OFFLOAD_BYTES:
                body_ref = await self.bodies.put(
                    self.user_context.workspace_id, task.id, row.event_id, content
                )
                content = ""
            tool_calls, meta = pg_storable(row.tool_calls), pg_storable(row.meta)
            if tool_calls is not None:
                encoded = json.dumps(tool_calls, ensure_ascii=False)
                if len(encoded.encode("utf-8")) > BODY_OFFLOAD_BYTES:
                    # A tool call's arguments (a file to save) are a body too.
                    ref = await self.bodies.put(
                        self.user_context.workspace_id,
                        task.id,
                        row.event_id,
                        encoded,
                        part=TOOL_CALLS_PART,
                    )
                    meta = {**(meta or {}), TOOL_CALLS_REF: ref}
                    tool_calls = None
            value = {
                "task_id": task.id,
                "seq": row.seq,
                "event_id": row.event_id,
                "kind": row.kind,
                "role": pg_storable(row.role),
                "content": content,
                "tool_calls": _jsonb(tool_calls),
                "tool_call_id": pg_storable(row.tool_call_id),
                "name": pg_storable(row.name),
                "attachments": _jsonb(row.attachments),
                "execution_id": execution_id,
                "iteration": row.iteration,
                "meta": _jsonb(meta),
                "correlation_id": task.correlation_id,
                "causation_id": task.causation_id,
                "body_ref": body_ref,
                "workspace_id": self.user_context.workspace_id,
                "created_by": self.user_context.user_id,
                "created_at": row.occurred_at if row.occurred_at is not None else func.now(),
            }
            values.append(value)
        await self.session.execute(
            pg_insert(TaskConversationEntryORM)
            .values(values)
            .on_conflict_do_nothing(constraint="uq_task_conversation_entries_event")
        )

    async def _set_outcome(self, task: Row[Any], outcome: TaskOutcome) -> None:
        fields: dict[str, Any] = {}
        if outcome.result is not None:
            fields["result"] = outcome.result
        fields.update(outcome.error_fields())
        if outcome.metadata_patch is not None:
            existing = task.task_metadata if isinstance(task.task_metadata, dict) else {}
            fields["metadata"] = {**existing, **outcome.metadata_patch}
        await TaskRepository(self.session, self.user_context).update_status(
            task.id, outcome.status, **fields
        )

    async def _resolved(self, entry: ConversationEntry) -> ConversationEntry:
        update: dict[str, Any] = {}
        if entry.body_ref is not None:
            update["content"] = await self.bodies.get(entry.body_ref)
        calls_ref = (entry.meta or {}).get(TOOL_CALLS_REF)
        if isinstance(calls_ref, str):
            update["tool_calls"] = json.loads(await self.bodies.get(calls_ref))
        return entry.model_copy(update=update) if update else entry


def _feed_rows() -> ColumnElement[bool]:
    entries = TaskConversationEntryORM
    return or_(entries.kind == "event", and_(entries.kind == "message", entries.role == "user"))


def _of_type(event_type: str) -> ColumnElement[bool]:
    entries = TaskConversationEntryORM
    if event_type == MESSAGE_RECEIVED:
        return and_(entries.kind == "message", entries.role == "user")
    return and_(entries.kind == "event", entries.name == event_type)


class TaskFeedReader:
    """The rows of one task's log its feed shows (``feed_event``), in ``seq`` order."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context

    def _scope(self, task_id: UUID) -> ColumnElement[bool]:
        entries = TaskConversationEntryORM
        return and_(
            entries.task_id == task_id,
            entries.workspace_id == self.user_context.workspace_id,
            _feed_rows(),
        )

    async def after(self, task_id: UUID, *, after_seq: int, limit: int) -> list[ConversationEntry]:
        """Up to ``limit`` feed rows past ``after_seq``."""
        entries = TaskConversationEntryORM
        result = await self.session.execute(
            select(entries)
            .where(self._scope(task_id), entries.seq > after_seq)
            .order_by(entries.seq)
            .limit(limit)
        )
        return [entry_from_row(row) for row in result.scalars().all()]

    async def page(
        self, task_id: UUID, *, event_type: str | None, limit: int, offset: int
    ) -> tuple[list[ConversationEntry], int]:
        """One page of feed rows, optionally of one type, and how many there are."""
        entries = TaskConversationEntryORM
        conditions = [self._scope(task_id)]
        if event_type:
            conditions.append(_of_type(event_type))
        total = (
            await self.session.scalar(select(func.count()).select_from(entries).where(*conditions))
        ) or 0
        result = await self.session.execute(
            select(entries).where(*conditions).order_by(entries.seq).limit(limit).offset(offset)
        )
        return [entry_from_row(row) for row in result.scalars().all()], total

    async def bodies(self, task_id: UUID, entries: Sequence[ConversationEntry]) -> FeedBodies:
        """The full tool arguments and results behind the tool events among ``entries``."""
        call_ids = {
            call_id
            for entry in entries
            if entry.kind == "event"
            and entry.name in (TOOL_CALL, TOOL_RESULT)
            and isinstance(call_id := (entry.meta or {}).get("tool_call_id"), str)
        }
        if not call_ids:
            return FeedBodies()
        rows = TaskConversationEntryORM
        result = await self.session.execute(
            select(rows).where(
                rows.task_id == task_id,
                rows.workspace_id == self.user_context.workspace_id,
                rows.kind == "message",
                or_(
                    and_(rows.role == "tool", rows.tool_call_id.in_(call_ids)),
                    and_(
                        rows.role == "assistant",
                        or_(*(rows.tool_calls.contains([{"id": call_id}]) for call_id in call_ids)),
                    ),
                ),
            )
        )
        return FeedBodies.of(entry_from_row(row) for row in result.scalars().all())

    async def at(self, task_id: UUID, seq: int) -> ConversationEntry | None:
        """The feed row at ``seq``, or None when that row is not one the feed shows."""
        entries = TaskConversationEntryORM
        row = await self.session.scalar(
            select(entries).where(self._scope(task_id), entries.seq == seq)
        )
        return entry_from_row(row) if row is not None else None

    async def latest_of_types(
        self, task_id: UUID, event_types: Sequence[str], *, limit: int
    ) -> list[ConversationEntry]:
        """The newest feed rows of the given types, newest first."""
        entries = TaskConversationEntryORM
        conditions = [self._scope(task_id)]
        if event_types:
            conditions.append(or_(*(_of_type(t) for t in event_types)))
        result = await self.session.execute(
            select(entries).where(*conditions).order_by(entries.seq.desc()).limit(limit)
        )
        return [entry_from_row(row) for row in result.scalars().all()]
