"""Task repository implementation."""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from typing import cast as type_cast
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_common.utils.pg_text import pg_storable
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.base_service import TaskNotFoundError
from ..domain.costs import CostCategory, CostEntry
from ..domain.models import ConversationEntry, Task, TaskCreate, TaskEvent, TaskUpdate
from ..domain.statuses import ENDED_TASK_STATUSES
from .cost_repository import CostEntryRepository, SpendScope
from .orm import TaskConversationEntryORM, TaskEventORM, TaskORM

if TYPE_CHECKING:
    from agentarea_governance.domain.policies import BudgetPolicy

    from ..spend_gate import LlmCapReached


class TaskRepository(WorkspaceScopedRepository[TaskORM]):
    """Repository for task persistence."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TaskORM, user_context)

    async def get_task(self, id: UUID) -> Task | None:
        """Get a task by ID and convert to domain model."""
        task_orm = await self.get_by_id(id)
        if not task_orm:
            return None
        return self._orm_to_domain(task_orm)

    async def list_tasks(
        self, limit: int = 100, offset: int = 0, created_by: str | None = None
    ) -> list[Task]:
        """List the workspace's tasks, or only those ``created_by`` started."""
        filters: dict[str, Any] = {} if created_by is None else {"created_by": created_by}
        task_orms = await self.list_all(limit=limit, offset=offset, **filters)
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        statuses: Sequence[str] = (),
        created_by: str | None = None,
        search: str | None = None,
        agent_ids: Sequence[UUID] = (),
        agent_id: UUID | None = None,
    ) -> list[TaskORM]:
        """One page of the workspace's tasks, newest first, filtered in SQL.

        ``search`` matches the description case-insensitively, or any task of an
        agent in ``agent_ids`` — agent names live in another table, so the caller
        passes the ids of the agents whose name matched. ``agent_id`` keeps only
        that agent's tasks.
        """
        query = select(TaskORM).where(self._get_workspace_filter())
        if statuses:
            query = query.where(TaskORM.status.in_(statuses))
        if created_by:
            query = query.where(TaskORM.created_by == created_by)
        if agent_id:
            query = query.where(TaskORM.agent_id == agent_id)
        if search:
            matches = TaskORM.description.icontains(search, autoescape=True)
            if agent_ids:
                matches = or_(matches, TaskORM.agent_id.in_(agent_ids))
            query = query.where(matches)
        query = (
            query.order_by(TaskORM.created_at.desc(), TaskORM.id.desc()).offset(offset).limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create_task(self, entity: Task) -> Task:
        """Create a new task from domain model."""
        # Handle metadata field - ensure it's JSON serializable
        metadata = entity.metadata
        if metadata is not None and not isinstance(metadata, dict):
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}

        # Extract fields from domain model
        task_data = {
            "id": entity.id,
            "agent_id": entity.agent_id,
            "description": entity.description,
            "parameters": entity.parameters,
            "status": entity.status,
            "result": entity.result,
            "error": entity.error,
            "started_at": entity.started_at,
            "completed_at": entity.completed_at,
            "scheduled_at": entity.scheduled_at,
            "execution_id": entity.execution_id,
            "task_metadata": metadata,
            "origin_type": entity.provenance.origin_type,
            "origin_id": entity.provenance.origin_id,
            # A task no event started (the API, A2A, a schedule) begins its own chain.
            "correlation_id": entity.provenance.correlation_id or str(entity.id),
            "causation_id": entity.provenance.causation_id,
            "parent_task_id": entity.provenance.parent_task_id,
        }

        # Remove None values and system fields that will be auto-populated
        task_data = {k: v for k, v in task_data.items() if v is not None}
        task_data.pop("created_at", None)
        task_data.pop("updated_at", None)

        task_orm = await self.create(**task_data)
        return self._orm_to_domain(task_orm)

    async def update_task(self, entity: Task) -> Task:
        """Update an existing task from domain model."""
        # Handle metadata field - ensure it's JSON serializable
        metadata = entity.metadata
        if metadata is not None and not isinstance(metadata, dict):
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}

        # Extract fields from domain model
        task_data = {
            "agent_id": entity.agent_id,
            "description": entity.description,
            "parameters": entity.parameters,
            "status": entity.status,
            "result": entity.result,
            "error": entity.error,
            "started_at": entity.started_at,
            "completed_at": entity.completed_at,
            "scheduled_at": entity.scheduled_at,
            "execution_id": entity.execution_id,
            "task_metadata": metadata,
        }

        # Remove None values
        task_data = {k: v for k, v in task_data.items() if v is not None}

        task_orm = await self.update(entity.id, **task_data)
        if not task_orm:
            # The row is gone (deleted, or outside this workspace). Returning the
            # entity here reported success for a write that never happened, and
            # left anything else flushed on this session — outbox rows included —
            # uncommitted and unrolled-back. Fail so the caller's transaction
            # unwinds with it.
            raise TaskNotFoundError(f"Task {entity.id} not found for update")
        return self._orm_to_domain(task_orm)

    async def delete_task(self, id: UUID) -> bool:
        """Delete a task by ID."""
        return await self.delete(id)

    # Additional methods for task-specific operations
    async def create_from_data(self, task_data: TaskCreate) -> Task:
        """Create a new task from TaskCreate data.

        Raises:
            ValueError: If the task carries no owner. Silently attributing it to
                whoever happened to make the call hides the caller's bug and
                hands the run an authority it was never given.
        """
        if not task_data.user_id:
            raise ValueError("TaskCreate.user_id is required; a task must name its owner")
        if not task_data.workspace_id:
            raise ValueError("TaskCreate.workspace_id is required; a task must name its tenant")

        # Handle metadata field - ensure it's JSON serializable
        metadata = task_data.metadata
        if metadata is not None and not isinstance(metadata, dict):
            # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
            metadata = {}

        task_orm = TaskORM(
            # BaseModel automatically provides: id, created_at, updated_at
            agent_id=task_data.agent_id,
            description=task_data.description,
            parameters=task_data.parameters,
            status="pending",
            created_by=task_data.user_id,
            workspace_id=task_data.workspace_id,
            task_metadata=metadata,
        )

        self.session.add(task_orm)
        await self.session.flush()
        await self.session.refresh(task_orm)

        result = self._orm_to_domain(task_orm)
        return result

    async def update_by_id(self, task_id: UUID, task_update: TaskUpdate) -> Task | None:
        """Update a task by ID with TaskUpdate data."""
        # Build update dict excluding None values
        update_data = {}
        for field, value in task_update.dict(exclude_unset=True).items():
            if value is not None:
                if field == "metadata":
                    # Handle metadata field - ensure it's JSON serializable
                    if value is not None and not isinstance(value, dict):
                        # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
                        value = {}
                    update_data["task_metadata"] = value
                elif field == "task_parameters":
                    # Domain field task_parameters maps to ORM column `parameters`.
                    update_data["parameters"] = value
                else:
                    update_data[field] = value

        if not update_data:
            return await self.get_task(task_id)

        stmt = (
            update(TaskORM)
            .where(TaskORM.id == task_id, self._get_workspace_filter())
            .values(**update_data)
        )
        await self.session.execute(stmt)
        await self.session.flush()

        return await self.get_task(task_id)

    async def get_by_agent_id(
        self, agent_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Task]:
        """Get tasks by agent ID with pagination."""
        stmt = (
            select(TaskORM)
            .where(self._get_workspace_filter())
            .where(TaskORM.agent_id == agent_id)
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()

        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def get_by_status(self, status: str) -> list[Task]:
        """Get tasks by status."""
        stmt = (
            select(TaskORM)
            .where(self._get_workspace_filter())
            .where(TaskORM.status == status)
            .order_by(TaskORM.created_at.desc())
        )
        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()

        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def list_by_statuses(
        self,
        statuses: list[str],
        agent_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks matching any of the given statuses, newest call for attention first.

        An ended task called for attention when its run ended, a waiting one when
        it began to wait. ``updated_at`` alone moves on any later write, such as
        a follow-up wait expiring half an hour after the run ended.
        """
        attention_at = case(
            (
                TaskORM.status.in_(ENDED_TASK_STATUSES),
                func.coalesce(TaskORM.completed_at, TaskORM.updated_at),
            ),
            else_=TaskORM.updated_at,
        )
        stmt = (
            select(TaskORM)
            .where(self._get_workspace_filter())
            .where(TaskORM.status.in_(statuses))
            .order_by(attention_at.desc(), TaskORM.id)
            .limit(limit)
            .offset(offset)
        )
        if agent_id is not None:
            stmt = stmt.where(TaskORM.agent_id == agent_id)

        result = await self.session.execute(stmt)
        task_orms = result.scalars().all()
        return [self._orm_to_domain(task_orm) for task_orm in task_orms]

    async def find_active_in_session(
        self, agent_id: UUID, trigger_id: str, session_key: str, limit: int = 5
    ) -> list[Task]:
        """Recent live tasks of a trigger and agent in one session, newest first.

        Used for follow-up routing: the next event of a session joins the task
        waiting in it instead of starting a new one.
        """
        stmt = (
            select(TaskORM)
            .where(
                self._get_workspace_filter(),
                TaskORM.agent_id == agent_id,
                TaskORM.status.in_(["running", "completed"]),
                TaskORM.execution_id.isnot(None),
                TaskORM.parameters["trigger_id"].as_string() == trigger_id,
                TaskORM.parameters["session"]["key"].as_string() == session_key,
            )
            .order_by(TaskORM.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [self._orm_to_domain(t) for t in result.scalars().all()]

    async def count_by_statuses(self, statuses: list[str], agent_id: UUID | None = None) -> int:
        """Count tasks matching any of the given statuses in the current workspace.

        ``agent_id`` narrows the count the way it narrows ``list_by_statuses``,
        so a filtered page and its total describe the same rows.
        """
        stmt = (
            select(func.count(TaskORM.id))
            .where(self._get_workspace_filter())
            .where(TaskORM.status.in_(statuses))
        )
        if agent_id is not None:
            stmt = stmt.where(TaskORM.agent_id == agent_id)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def sum_spend_since(self, since: datetime, agent_id: UUID | None = None) -> Decimal:
        """The workspace's spend since a UTC instant, in the billing currency.

        Summed from the spend ledger, where each paid line is stored once on the
        task that incurred it, so delegated child spend is never counted twice.
        ``agent_id`` narrows the sum to one agent's lines.
        """
        return await CostEntryRepository(self.session, self.user_context).sum_since(
            since,
            currency=get_customer_pricing().currency(),
            agent_id=agent_id,
        )

    async def monthly_llm_cap_reached(
        self, budget: "BudgetPolicy | None", agent_id: UUID | None = None
    ) -> "LlmCapReached | None":
        """The first monthly cap on LLM spend that this month's model lines reached."""
        from ..spend_gate import monthly_llm_cap_reached

        return await monthly_llm_cap_reached(
            CostEntryRepository(self.session, self.user_context),
            budget,
            agent_id,
            get_customer_pricing().currency(),
        )

    async def sum_task_llm_spend(self, task_id: UUID) -> Decimal:
        """What a task's own model calls cost over all its runs, in the billing currency."""
        return await CostEntryRepository(self.session, self.user_context).sum_since(
            datetime(1970, 1, 1, tzinfo=UTC),
            currency=get_customer_pricing().currency(),
            scope=SpendScope(task_id=task_id, category=CostCategory.MODEL),
        )

    async def sum_task_spend(self, task_id: UUID) -> Decimal:
        """What a task cost over all its runs, every line of it, in the billing currency."""
        return await CostEntryRepository(self.session, self.user_context).sum_since(
            datetime(1970, 1, 1, tzinfo=UTC),
            currency=get_customer_pricing().currency(),
            scope=SpendScope(task_id=task_id),
        )

    async def record_costs(self, entries: Sequence[CostEntry]) -> None:
        """Store paid lines in the spend ledger, once each."""
        await CostEntryRepository(self.session, self.user_context).record(entries)

    async def sum_spend_by_day(
        self, since: datetime, agent_id: UUID | None = None
    ) -> dict[date, Decimal]:
        """The workspace's (or one agent's) spend per UTC day since a UTC instant."""
        return await CostEntryRepository(self.session, self.user_context).sum_by_day(
            since,
            currency=get_customer_pricing().currency(),
            agent_id=agent_id,
        )

    async def sum_spend_mtd(self, agent_id: UUID | None = None) -> Decimal:
        """The workspace's (or one agent's) spend since the first of this UTC month."""
        now = datetime.now(UTC)
        return await self.sum_spend_since(datetime(now.year, now.month, 1, tzinfo=UTC), agent_id)

    async def sum_spend_today(self) -> Decimal:
        """The workspace's spend since the start of today UTC."""
        now = datetime.now(UTC)
        return await self.sum_spend_since(datetime(now.year, now.month, now.day, tzinfo=UTC))

    async def update_status(self, task_id: UUID, status: str, **additional_fields) -> Task | None:
        """Update task status atomically with optional additional fields.

        Entering ``running`` stamps when the run first started; ending stamps when it
        last ended. Writing an ended status the task already has keeps that stamp:
        the run ended then, not when its workflow later closed.
        """
        now = datetime.now(UTC).replace(tzinfo=None)
        update_data: dict[str, Any] = {"status": status, "updated_at": now}
        if status == "running":
            update_data["started_at"] = func.coalesce(TaskORM.started_at, now)
        elif status in ENDED_TASK_STATUSES:
            update_data["completed_at"] = case(
                (TaskORM.status == status, func.coalesce(TaskORM.completed_at, now)),
                else_=now,
            )

        # Add any additional fields provided
        for field, value in additional_fields.items():
            if field == "metadata":
                # Handle metadata field - ensure it's JSON serializable
                if value is not None and not isinstance(value, dict):
                    # If it's not a dict (e.g., SQLAlchemy MetaData), convert to empty dict
                    value = {}
                update_data["task_metadata"] = value
            else:
                update_data[field] = value

        stmt = (
            update(TaskORM)
            .where(TaskORM.id == task_id, self._get_workspace_filter())
            .values(**update_data)
        )
        result = await self.session.execute(stmt)

        if type_cast(CursorResult[Any], result).rowcount == 0:
            return None

        await self.session.flush()
        return await self.get_task(task_id)

    async def merge_metadata(self, task_id: UUID, patch: dict[str, Any]) -> bool:
        """Shallow-merge ``patch`` into the task's metadata, leaving status alone.

        Returns False when the task no longer exists.
        """
        task_orm = await self.session.get(TaskORM, task_id)
        if task_orm is None or task_orm.workspace_id != self.user_context.workspace_id:
            return False

        existing = task_orm.task_metadata if isinstance(task_orm.task_metadata, dict) else {}
        stmt = (
            update(TaskORM)
            .where(TaskORM.id == task_id)
            .where(TaskORM.workspace_id == self.user_context.workspace_id)
            .values(task_metadata={**existing, **patch}, updated_at=datetime.utcnow())
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return True

    def _orm_to_domain(self, task_orm: TaskORM) -> Task:
        """Convert ORM model to domain model."""
        task_metadata = task_orm.task_metadata or {}

        # Ensure metadata is always a dict
        if not isinstance(task_metadata, dict):
            task_metadata = {}

        return Task.model_validate(
            {
                "id": task_orm.id,
                "agent_id": task_orm.agent_id,
                "description": task_orm.description,
                "parameters": task_orm.parameters or {},
                "status": task_orm.status,
                "result": task_orm.result,
                "error": task_orm.error,
                "created_at": task_orm.created_at,
                "updated_at": task_orm.updated_at,  # Added to match BaseModel
                "started_at": task_orm.started_at,
                "completed_at": task_orm.completed_at,
                "scheduled_at": task_orm.scheduled_at,
                "execution_id": task_orm.execution_id,
                "user_id": task_orm.created_by,
                "workspace_id": task_orm.workspace_id,
                "metadata": task_metadata,
                "provenance": {
                    "origin_type": task_orm.origin_type,
                    "origin_id": task_orm.origin_id,
                    "correlation_id": task_orm.correlation_id,
                    "causation_id": task_orm.causation_id,
                    "parent_task_id": task_orm.parent_task_id,
                },
            }
        )


class TaskEventRepository(WorkspaceScopedRepository[TaskEventORM]):
    """Writes the old ``task_events`` table, which only the enterprise usage emitter reads.

    The task feed reads the task log (``task_log.TaskFeedReader``).
    """

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TaskEventORM, user_context)

    async def create_event(self, event: TaskEvent) -> TaskEvent:
        """Store a task event once per id and return the stored row.

        Storing an id that already exists is a no-op that returns the first
        write, so a retried publish cannot duplicate history.
        """
        if event.workspace_id != self.user_context.workspace_id:
            raise ValueError(
                f"Task event {event.id} belongs to workspace {event.workspace_id}, "
                f"not {self.user_context.workspace_id}"
            )
        await self.session.execute(
            pg_insert(TaskEventORM)
            .values(
                id=event.id,
                task_id=event.task_id,
                event_type=event.event_type,
                timestamp=event.timestamp,
                data=pg_storable(event.data),
                event_metadata=pg_storable(event.metadata),
                workspace_id=event.workspace_id,
                created_by=event.created_by,
            )
            .on_conflict_do_nothing(index_elements=[TaskEventORM.id])
        )
        stored = await self.session.scalar(
            select(TaskEventORM)
            .where(TaskEventORM.id == event.id, self._get_workspace_filter())
            .execution_options(populate_existing=True)
        )
        if stored is None or stored.task_id != event.task_id:
            raise ValueError(f"Task event id {event.id} is already stored for another task")
        return self._orm_to_domain(stored)

    def _orm_to_domain(self, event_orm: TaskEventORM) -> TaskEvent:
        """Convert ORM model to domain model."""
        return TaskEvent.model_validate(
            {
                "id": event_orm.id,
                "task_id": event_orm.task_id,
                "event_type": event_orm.event_type,
                "timestamp": event_orm.timestamp,
                "data": event_orm.data or {},
                "metadata": event_orm.event_metadata or {},
                "workspace_id": event_orm.workspace_id,
                "created_by": event_orm.created_by,
            }
        )


class TaskConversationRepository(WorkspaceScopedRepository[TaskConversationEntryORM]):
    """A task's model conversation, stored outside the execution engine."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, TaskConversationEntryORM, user_context)

    async def write(self, task_id: UUID, entries: Sequence[ConversationEntry]) -> None:
        """Store entries at their sequence numbers; writing a position again replaces it.

        Positions are assigned deterministically — by the workflow, or by the
        API before it resumes a closed conversation — so a retry rewrites the
        same entry and a later write is the current truth.
        """
        if not entries:
            return
        rows = [
            {
                "task_id": task_id,
                "seq": entry.seq,
                "event_id": entry.event_id or uuid4(),
                "kind": entry.kind,
                "role": entry.role,
                "content": pg_storable(entry.content),
                "tool_calls": pg_storable(entry.tool_calls),
                "tool_call_id": pg_storable(entry.tool_call_id),
                "name": pg_storable(entry.name),
                "attachments": pg_storable(entry.attachments),
                "iteration": entry.iteration,
                "meta": pg_storable(entry.meta),
                "workspace_id": self.user_context.workspace_id,
                "created_by": self.user_context.user_id,
            }
            for entry in entries
        ]
        statement = pg_insert(TaskConversationEntryORM).values(rows)
        await self.session.execute(
            statement.on_conflict_do_update(
                constraint="uq_task_conversation_entries_seq",
                set_={
                    column: statement.excluded[column]
                    for column in (
                        "kind",
                        "role",
                        "content",
                        "tool_calls",
                        "tool_call_id",
                        "name",
                        "attachments",
                        "iteration",
                        "meta",
                    )
                },
                where=TaskConversationEntryORM.workspace_id == self.user_context.workspace_id,
            )
        )

    async def read(
        self, task_id: UUID, *, head_seqs: Sequence[int], tail_start: int, end_seq: int
    ) -> tuple[list[ConversationEntry], list[ConversationEntry]]:
        """The head entries in the given order and the tail ``[tail_start, end_seq)``.

        A tail entry that is also in the head is returned once, in the head.
        """
        result = await self.session.execute(
            select(TaskConversationEntryORM).where(
                TaskConversationEntryORM.task_id == task_id,
                self._get_workspace_filter(),
                or_(
                    TaskConversationEntryORM.seq.in_(list(head_seqs)),
                    (TaskConversationEntryORM.seq >= tail_start)
                    & (TaskConversationEntryORM.seq < end_seq),
                ),
            )
        )
        by_seq = {row.seq: self._orm_to_entry(row) for row in result.scalars().all()}
        missing = [seq for seq in head_seqs if seq not in by_seq]
        if missing:
            raise LookupError(f"task {task_id} conversation has no entries at {missing}")
        head = [by_seq[seq] for seq in head_seqs]
        head_set = set(head_seqs)
        tail = [by_seq[seq] for seq in sorted(by_seq) if seq >= tail_start and seq not in head_set]
        return head, tail

    async def next_seq(self, task_id: UUID) -> int:
        """The position after the task's last entry; 0 for an empty log."""
        last = await self.session.scalar(
            select(func.max(TaskConversationEntryORM.seq)).where(
                TaskConversationEntryORM.task_id == task_id, self._get_workspace_filter()
            )
        )
        return 0 if last is None else last + 1

    async def has_messages_from(self, task_id: UUID, seq: int) -> bool:
        """Whether the log holds a message, not an event row, at ``seq`` or after it."""
        found = await self.session.scalar(
            select(TaskConversationEntryORM.seq)
            .where(
                TaskConversationEntryORM.task_id == task_id,
                self._get_workspace_filter(),
                TaskConversationEntryORM.seq >= seq,
                TaskConversationEntryORM.kind != "event",
            )
            .limit(1)
        )
        return found is not None

    async def read_all(self, task_id: UUID) -> list[ConversationEntry]:
        """Every entry of the task's conversation, in log order."""
        result = await self.session.execute(
            select(TaskConversationEntryORM)
            .where(TaskConversationEntryORM.task_id == task_id, self._get_workspace_filter())
            .order_by(TaskConversationEntryORM.seq)
        )
        return [self._orm_to_entry(row) for row in result.scalars().all()]

    @staticmethod
    def _orm_to_entry(row: TaskConversationEntryORM) -> ConversationEntry:
        return entry_from_row(row)


def entry_from_row(row: TaskConversationEntryORM) -> ConversationEntry:
    """A stored log row as the domain entry; an offloaded body stays a reference."""
    return ConversationEntry(
        seq=row.seq,
        kind=row.kind,
        role=row.role,
        content=row.content,
        tool_calls=row.tool_calls,
        tool_call_id=row.tool_call_id,
        name=row.name,
        attachments=row.attachments,
        event_id=row.event_id,
        execution_id=row.execution_id,
        iteration=row.iteration,
        meta=row.meta,
        correlation_id=row.correlation_id,
        causation_id=row.causation_id,
        body_ref=row.body_ref,
        occurred_at=row.created_at,
    )
