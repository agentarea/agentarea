"""Read raw usage facts; no public ingestion or billing calculations."""

import json
from typing import Annotated

from agentarea_common.auth import UserContextDep
from agentarea_common.config.database import get_db_session
from agentarea_common.usage.models import ResourceUsageEvent
from agentarea_common.usage.repository import UsageRepository, UsageTimeBound
from agentarea_common.utils.types import UtcDatetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/usage", tags=["usage"])
DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


class UsageEventResponse(BaseModel):
    sequence: str
    id: str
    schema_version: int
    source: str
    kind: str
    workspace_id: str
    resource_kind: str
    resource_id: str
    incarnation_id: str
    task_id: str
    # Keep the source nanoseconds; datetime would truncate to microseconds.
    occurred_at: str
    received_at: UtcDatetime
    # Raw JSON text prevents JS clients from silently rounding uint64 counters.
    data_json: str

    @classmethod
    def from_event(cls, event: ResourceUsageEvent) -> "UsageEventResponse":
        return cls(
            sequence=str(event.sequence),
            id=event.event_id,
            schema_version=event.schema_version,
            source=event.source,
            kind=event.kind,
            workspace_id=event.workspace_id,
            resource_kind=event.resource_kind,
            resource_id=event.resource_id,
            incarnation_id=event.incarnation_id,
            task_id=event.task_id,
            occurred_at=event.occurred_at_source,
            received_at=event.received_at,
            data_json=json.dumps(event.data, separators=(",", ":"), ensure_ascii=False),
        )


class UsageEventListResponse(BaseModel):
    events: list[UsageEventResponse]
    next_cursor: str | None


@router.get("/events", response_model=UsageEventListResponse)
async def list_usage_events(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    source: str | None = Query(None),
    kind: str | None = Query(None),
    resource_kind: str | None = Query(None),
    resource_id: str | None = Query(None),
    task_id: str | None = Query(None),
    since: str | None = Query(None, alias="from"),
    until: str | None = Query(None),
    cursor: str | None = Query(None, pattern=r"^[1-9]\d{0,18}$"),
    limit: int = Query(50, ge=1, le=100),
) -> UsageEventListResponse:
    """Return newest persisted facts first, scoped to the current workspace."""
    try:
        lower = UsageTimeBound.parse(since) if since is not None else None
        upper = UsageTimeBound.parse(until) if until is not None else None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cursor_value = int(cursor) if cursor is not None else None
    if cursor_value is not None and cursor_value > 9223372036854775807:
        raise HTTPException(status_code=422, detail="Usage cursor exceeds the stored sequence range")
    if lower is not None and upper is not None and lower.exact > upper.exact:
        raise HTTPException(status_code=422, detail="from must not be after until")
    repo = UsageRepository(db_session, user_context)
    events = await repo.query(
        source=source,
        kind=kind,
        resource_kind=resource_kind,
        resource_id=resource_id,
        task_id=task_id,
        since=lower,
        until=upper,
        cursor=cursor_value,
        limit=limit + 1,
    )
    has_more = len(events) > limit
    page = events[:limit]
    return UsageEventListResponse(
        events=[UsageEventResponse.from_event(event) for event in page],
        next_cursor=str(page[-1].sequence) if has_more else None,
    )
