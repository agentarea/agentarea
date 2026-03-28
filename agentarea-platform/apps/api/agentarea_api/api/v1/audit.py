"""Audit log API endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from agentarea_common.auth import UserContextDep
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.audit.repository import AuditRepository
from agentarea_common.infrastructure.database import get_db_session
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditEventResponse(BaseModel):
    """Audit event response schema."""

    id: UUID
    created_at: datetime
    actor_id: str
    actor_type: str
    workspace_id: str
    source_ip: str | None
    user_agent: str | None
    request_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    changes: list[dict] | None
    event_metadata: dict

    @classmethod
    def from_orm(cls, event: AuditEventORM) -> "AuditEventResponse":
        return cls(
            id=event.id,
            created_at=event.created_at,
            actor_id=event.actor_id,
            actor_type=event.actor_type,
            workspace_id=event.workspace_id,
            source_ip=str(event.source_ip) if event.source_ip else None,
            user_agent=event.user_agent,
            request_id=event.request_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            changes=event.changes,
            event_metadata=event.event_metadata,
        )


class AuditLogListResponse(BaseModel):
    """Paginated audit log response."""

    events: list[AuditEventResponse]
    next_cursor: str | None


DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/", response_model=AuditLogListResponse)
async def list_audit_logs(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    action: str | None = Query(None, description="Filter by action (e.g. agent.create)"),
    actor_id: str | None = Query(None, description="Filter by actor ID"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    resource_id: str | None = Query(None, description="Filter by resource ID"),
    since: datetime | None = Query(None, description="Events after this time (ISO 8601)"),
    until: datetime | None = Query(None, description="Events before this time (ISO 8601)"),
    cursor: UUID | None = Query(None, description="Cursor for pagination"),
    limit: int = Query(50, ge=1, le=100, description="Max events to return"),
):
    """List audit events for the current workspace."""
    repo = AuditRepository(db_session)
    events = await repo.query(
        workspace_id=user_context.workspace_id,
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        resource_id=resource_id,
        since=since,
        until=until,
        cursor=cursor,
        limit=limit,
    )

    next_cursor = str(events[-1].id) if events else None

    return AuditLogListResponse(
        events=[AuditEventResponse.from_orm(e) for e in events],
        next_cursor=next_cursor,
    )
