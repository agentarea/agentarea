"""Persistence of the spend ledger."""

from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.money import ZERO
from sqlalchemy import Date, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..domain.costs import CostEntry
from .orm import CostEntryORM


class CostEntryRepository(WorkspaceScopedRepository[CostEntryORM]):
    """Append-only store of a workspace's paid lines."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, CostEntryORM, user_context)

    async def record(self, entries: Sequence[CostEntry]) -> None:
        """Store each line once per (event, category); a repeated line is a no-op."""
        if not entries:
            return
        for entry in entries:
            if entry.workspace_id != self.user_context.workspace_id:
                raise ValueError(
                    f"Cost entry of event {entry.event_id} belongs to workspace "
                    f"{entry.workspace_id}, not {self.user_context.workspace_id}"
                )
        await self.session.execute(
            pg_insert(CostEntryORM)
            .values(
                [
                    {
                        "id": uuid4(),
                        "workspace_id": entry.workspace_id,
                        "created_by": entry.created_by,
                        "event_id": entry.event_id,
                        "category": entry.category.value,
                        "task_id": entry.task_id,
                        "agent_id": entry.agent_id,
                        "client_id": entry.client_id,
                        "subject_type": entry.subject_type.value,
                        "subject_id": entry.subject_id,
                        "subject_name": entry.subject_name,
                        "call_ref": entry.call_ref,
                        "amount": entry.amount,
                        "currency": entry.currency,
                        "provider_cost_usd": entry.provider_cost_usd,
                        "managed_by": entry.managed_by,
                        "source": entry.source.value,
                        "evidence": entry.evidence,
                        "supersedes_id": entry.supersedes_id,
                        "occurred_at": entry.occurred_at,
                    }
                    for entry in entries
                ]
            )
            .on_conflict_do_nothing(index_elements=[CostEntryORM.event_id, CostEntryORM.category])
        )

    def _current_lines_since(self, since: datetime, currency: str, agent_id: UUID | None):
        newer = aliased(CostEntryORM)
        conditions = [
            self._get_workspace_filter(),
            CostEntryORM.occurred_at >= since,
            or_(CostEntryORM.currency == currency, CostEntryORM.currency.is_(None)),
            ~exists().where(newer.supersedes_id == CostEntryORM.id),
        ]
        if agent_id is not None:
            conditions.append(CostEntryORM.agent_id == agent_id)
        return conditions

    async def sum_by_day(
        self,
        since: datetime,
        *,
        currency: str,
        agent_id: UUID | None = None,
    ) -> dict[date, Decimal]:
        """Totals of current lines per UTC calendar day since a UTC instant."""
        day = cast(func.timezone("UTC", CostEntryORM.occurred_at), Date)
        rows = await self.session.execute(
            select(day.label("day"), func.sum(CostEntryORM.amount))
            .where(*self._current_lines_since(since, currency, agent_id))
            .group_by(day)
        )
        return {row[0]: Decimal(row[1]) for row in rows}

    async def sum_since(
        self,
        since: datetime,
        *,
        currency: str,
        agent_id: UUID | None = None,
    ) -> Decimal:
        """Total of the workspace's current lines in ``currency`` since a UTC instant.

        A line another line supersedes no longer counts. Lines in another
        currency are not converted and do not count.
        """
        stmt = select(func.coalesce(func.sum(CostEntryORM.amount), ZERO)).where(
            *self._current_lines_since(since, currency, agent_id)
        )
        return Decimal(await self.session.scalar(stmt) or ZERO)
