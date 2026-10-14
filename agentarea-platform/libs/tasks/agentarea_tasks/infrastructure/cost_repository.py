"""Persistence of the spend ledger."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.money import ZERO
from sqlalchemy import Date, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..domain.costs import CostCategory, CostEntry
from .orm import CostEntryORM


@dataclass(frozen=True)
class SpendScope:
    """Which lines a sum counts: the workspace's, narrowed by any field that is set.

    ``tool`` narrows a ``connection_id`` scope to the lines of one of its tools;
    ``category`` to model or tool lines; ``task_id`` to one run's; ``estimate`` to
    the lines whose amount is or is not final yet.
    """

    agent_id: UUID | None = None
    client_id: UUID | None = None
    connection_id: str | None = None
    tool: str | None = None
    task_id: UUID | None = None
    category: CostCategory | None = None
    estimate: bool | None = None


class CrossWorkspaceCostLines:
    """The one ledger read that spans every workspace: lines waiting to be settled.

    Run inside an ``unscoped`` block; each claimed line is then settled in its own
    workspace's scope. Never commits.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def claim_unsettled(
        self,
        *,
        now: datetime,
        since: datetime,
        tick: timedelta,
        max_interval: timedelta,
        limit: int,
    ) -> list[CostEntryORM]:
        """Lines marked for settlement, superseded by none, due now; locked SKIP LOCKED.

        A line is retried every tick while young, then about every tenth of its age
        (a power-of-two number of ticks), up to ``max_interval``: due when such an
        interval boundary passed in the last tick.
        Lines older than ``since`` are left as they are.
        """
        newer = aliased(CostEntryORM)
        seconds = tick.total_seconds()
        age = func.extract("epoch", now - CostEntryORM.occurred_at)
        # A tenth of the age, rounded down to a power-of-two number of ticks: an
        # interval that stays put between claims, so its boundaries fall once each.
        ticks = func.power(
            2, func.floor(func.ln(func.greatest(age / (10 * seconds), 1)) / math.log(2))
        )
        interval = func.least(ticks * seconds, max_interval.total_seconds())
        epoch = now.timestamp()
        due = func.floor(epoch / interval) != func.floor((epoch - tick.total_seconds()) / interval)
        rows = await self._session.execute(
            select(CostEntryORM)
            .where(
                CostEntryORM.evidence.has_key("settle"),
                CostEntryORM.occurred_at >= since,
                ~exists().where(newer.supersedes_id == CostEntryORM.id),
                due,
            )
            .order_by(CostEntryORM.occurred_at)
            .limit(limit)
            .with_for_update(skip_locked=True, of=CostEntryORM)
        )
        return list(rows.scalars().all())


class CostEntryRepository(WorkspaceScopedRepository[CostEntryORM]):
    """Append-only store of a workspace's paid lines."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, CostEntryORM, user_context)

    async def record(self, entries: Sequence[CostEntry]) -> int:
        """Store each line once per (event, category); returns how many were new.

        A repeated line is a no-op and does not count.
        """
        if not entries:
            return 0
        for entry in entries:
            if entry.workspace_id != self.user_context.workspace_id:
                raise ValueError(
                    f"Cost entry of event {entry.event_id} belongs to workspace "
                    f"{entry.workspace_id}, not {self.user_context.workspace_id}"
                )
        result = await self.session.execute(
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
                        "payer": entry.payer.value,
                        "quantity": entry.quantity,
                        "unit": entry.unit,
                        "vendor_cost": entry.vendor_cost,
                        "vendor_currency": entry.vendor_currency,
                        "source": entry.source.value,
                        "evidence": entry.evidence,
                        "supersedes_id": entry.supersedes_id,
                        "occurred_at": entry.occurred_at,
                        "estimate": entry.estimate,
                    }
                    for entry in entries
                ]
            )
            .on_conflict_do_nothing(index_elements=[CostEntryORM.event_id, CostEntryORM.category])
            .returning(CostEntryORM.id)
        )
        return len(result.all())

    def _current_lines_since(
        self, since: datetime, currency: str | None, scope: SpendScope
    ) -> list[Any]:
        newer = aliased(CostEntryORM)
        conditions: list[Any] = [
            self._get_workspace_filter(),
            CostEntryORM.occurred_at >= since,
            ~exists().where(newer.supersedes_id == CostEntryORM.id),
        ]
        if currency is not None:
            conditions.append(
                or_(CostEntryORM.currency == currency, CostEntryORM.currency.is_(None))
            )
        if scope.agent_id is not None:
            conditions.append(CostEntryORM.agent_id == scope.agent_id)
        if scope.client_id is not None:
            conditions.append(CostEntryORM.client_id == scope.client_id)
        if scope.connection_id is not None:
            conditions.append(CostEntryORM.subject_type == "tool")
            conditions.append(CostEntryORM.subject_id == scope.connection_id)
        if scope.tool is not None:
            conditions.append(CostEntryORM.subject_name == scope.tool)
        if scope.task_id is not None:
            conditions.append(CostEntryORM.task_id == scope.task_id)
        if scope.category is not None:
            conditions.append(CostEntryORM.category == scope.category.value)
        if scope.estimate is not None:
            conditions.append(CostEntryORM.estimate.is_(scope.estimate))
        return conditions

    async def sum_by_currency_since(
        self, since: datetime, scope: SpendScope | None = None
    ) -> dict[str | None, Decimal]:
        """Totals of the current lines since a UTC instant, per currency.

        ``None`` is the backfilled lines' currency: the deployment's billing currency.
        """
        rows = await self.session.execute(
            select(CostEntryORM.currency, func.sum(CostEntryORM.amount))
            .where(*self._current_lines_since(since, None, scope or SpendScope()))
            .group_by(CostEntryORM.currency)
        )
        return {row[0]: Decimal(row[1]) for row in rows}

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
            .where(*self._current_lines_since(since, currency, SpendScope(agent_id=agent_id)))
            .group_by(day)
        )
        return {row[0]: Decimal(row[1]) for row in rows}

    async def sum_since(
        self,
        since: datetime,
        *,
        currency: str,
        agent_id: UUID | None = None,
        scope: SpendScope | None = None,
    ) -> Decimal:
        """Total of the workspace's current lines in ``currency`` since a UTC instant.

        A line another line supersedes no longer counts. Lines in another
        currency are not converted and do not count. ``scope`` narrows the sum;
        ``agent_id`` is the agent-only scope.
        """
        stmt = select(func.coalesce(func.sum(CostEntryORM.amount), ZERO)).where(
            *self._current_lines_since(since, currency, scope or SpendScope(agent_id=agent_id))
        )
        return Decimal(await self.session.scalar(stmt) or ZERO)


async def record_cost_lines(user_context: UserContext, entries: Sequence[CostEntry]) -> int:
    """Store lines for spend outside a run (a trigger's model call) in a committed session."""
    from agentarea_common.config import get_database

    session = get_database().async_session_factory()
    try:
        recorded = await CostEntryRepository(session, user_context).record(entries)
        await session.commit()
        return recorded
    finally:
        await session.close()
