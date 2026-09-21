"""Read-only access to raw resource observations within an authenticated workspace."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_common.auth.context import UserContext

from .models import ResourceUsageEvent


@dataclass(frozen=True)
class UsageTimeBound:
    indexed: datetime
    exact: str

    @classmethod
    def parse(cls, value: str) -> "UsageTimeBound":
        match = re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d{1,9}))?(?:Z|[+-]\d{2}:\d{2})",
            value,
        )
        if match is None:
            raise ValueError(
                "Usage time filters require RFC3339 with at most nine fractional digits"
            )
        indexed = datetime.fromisoformat(value).astimezone(UTC)
        fraction = (match.group(1) or "").ljust(9, "0")
        second = indexed.isoformat(timespec="seconds").removesuffix("+00:00")
        return cls(indexed=indexed, exact=f"{second}.{fraction}Z")


class UsageRepository:
    def __init__(self, session: AsyncSession, user_context: UserContext):
        if not isinstance(user_context, UserContext) or not user_context.workspace_id:
            raise ValueError("Usage reads require an authenticated workspace context")
        self._session = session
        self._workspace_id = user_context.workspace_id

    async def query(
        self,
        *,
        source: str | None = None,
        kind: str | None = None,
        resource_kind: str | None = None,
        resource_id: str | None = None,
        task_id: str | None = None,
        since: UsageTimeBound | None = None,
        until: UsageTimeBound | None = None,
        cursor: int | None = None,
        limit: int = 50,
    ) -> list[ResourceUsageEvent]:
        if not 1 <= limit <= 101:
            raise ValueError("Usage page size must be between 1 and 101")
        if cursor is not None and not 0 < cursor <= 9223372036854775807:
            raise ValueError("Invalid usage cursor")
        stmt = (
            select(ResourceUsageEvent)
            .where(ResourceUsageEvent.workspace_id == self._workspace_id)
            .order_by(ResourceUsageEvent.sequence.desc())
            .limit(limit)
        )
        for column, value in (
            (ResourceUsageEvent.source, source),
            (ResourceUsageEvent.kind, kind),
            (ResourceUsageEvent.resource_kind, resource_kind),
            (ResourceUsageEvent.resource_id, resource_id),
            (ResourceUsageEvent.task_id, task_id),
        ):
            if value is not None:
                stmt = stmt.where(column == value)
        if since is not None or until is not None:
            # Go writers normalize source timestamps to UTC. Pad only their
            # fractional representation; never round the observed instant.
            source_time = func.concat(
                func.substr(ResourceUsageEvent.occurred_at_source, 1, 19),
                ".",
                func.rpad(
                    func.coalesce(
                        func.substring(ResourceUsageEvent.occurred_at_source, r"\.([0-9]+)Z$"),
                        "",
                    ),
                    9,
                    "0",
                ),
                "Z",
            )
            if since is not None:
                stmt = stmt.where(
                    ResourceUsageEvent.occurred_at >= since.indexed,
                    source_time >= since.exact,
                )
            if until is not None:
                stmt = stmt.where(
                    ResourceUsageEvent.occurred_at <= until.indexed,
                    source_time <= until.exact,
                )
        if cursor is not None:
            # No unscoped cursor-row lookup: even a foreign sequence can only
            # constrain rows already belonging to the authenticated workspace.
            stmt = stmt.where(ResourceUsageEvent.sequence < cursor)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
