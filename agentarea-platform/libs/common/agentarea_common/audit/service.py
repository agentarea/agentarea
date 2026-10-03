"""Audit service — writes to DB, optionally streams to enterprise sinks."""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.context import UserContext
from ..extensions.registry import ExtensionRegistry
from .context import get_audit_context
from .models import AuditEventORM
from .repository import AuditRepository

logger = logging.getLogger(__name__)


class AuditService:
    """Records audit events to the database.

    If an enterprise ``audit_sink`` extension is registered, events
    are also forwarded to external systems (SIEM, S3, etc.).
    """

    def __init__(self, session: AsyncSession, user_context: UserContext):
        self._repository = AuditRepository(session)
        self._user_context = user_context

    async def record(
        self,
        action: str,
        resource_type: str,
        resource_id: str | UUID | None = None,
        *,
        changes: list[dict[str, Any]] | None = None,
        actor_type: str = "user",
        actor_id: str | None = None,
        event_metadata: dict[str, Any] | None = None,
    ) -> AuditEventORM:
        """Record an audit event.

        Args:
            action: Hierarchical action name (e.g. "agent.create", "mcp.config.update")
            resource_type: Resource type (e.g. "agent", "mcp_server", "trigger")
            resource_id: ID of the affected resource
            changes: List of field changes [{field, before, after}]
            actor_type: Type of actor ("user", "agent", "client", "api_key", "system")
            actor_id: Who acted, when not the context's user (e.g. the agent making
                a tool call on a user's behalf)
            event_metadata: Additional context
        """
        event = self._build(
            action,
            resource_type,
            resource_id,
            changes=changes,
            actor_type=actor_type,
            actor_id=actor_id,
            event_metadata=event_metadata,
        )
        event = await self._repository.insert(event)
        await self._forward(event)
        return event

    async def record_once(
        self,
        event_id: UUID,
        action: str,
        resource_type: str,
        resource_id: str | UUID | None = None,
        *,
        actor_type: str = "user",
        actor_id: str | None = None,
        event_metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Record an event under a caller-chosen id, at most once.

        For writers that are retried whole, such as Temporal activities: derive
        ``event_id`` from the source fact so a retry is a no-op. Returns whether
        the row was written now.
        """
        event = self._build(
            action,
            resource_type,
            resource_id,
            changes=None,
            actor_type=actor_type,
            actor_id=actor_id,
            event_metadata=event_metadata,
        )
        event.id = event_id
        inserted = await self._repository.insert_once(event)
        if inserted:
            await self._forward(event)
        return inserted

    def _build(
        self,
        action: str,
        resource_type: str,
        resource_id: str | UUID | None,
        *,
        changes: list[dict[str, Any]] | None,
        actor_type: str,
        actor_id: str | None,
        event_metadata: dict[str, Any] | None,
    ) -> AuditEventORM:
        ctx = get_audit_context()
        return AuditEventORM(
            actor_id=actor_id or self._user_context.user_id,
            actor_type=actor_type,
            workspace_id=self._user_context.workspace_id,
            source_ip=ctx.source_ip,
            user_agent=ctx.user_agent,
            request_id=ctx.request_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            changes=changes,
            event_metadata=event_metadata or {},
        )

    async def _forward(self, event: AuditEventORM) -> None:
        """Forward to the enterprise audit sink, if one is registered."""
        sink_factory = ExtensionRegistry.get_factory("audit_sink")
        if sink_factory:
            try:
                sink = sink_factory()
                await sink.emit(event.to_dict())
            except Exception:
                logger.warning("Failed to forward audit event to enterprise sink", exc_info=True)
