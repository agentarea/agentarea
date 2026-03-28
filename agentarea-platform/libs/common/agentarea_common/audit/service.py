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
        event_metadata: dict[str, Any] | None = None,
    ) -> AuditEventORM:
        """Record an audit event.

        Args:
            action: Hierarchical action name (e.g. "agent.create", "mcp.config.update")
            resource_type: Resource type (e.g. "agent", "mcp_server", "trigger")
            resource_id: ID of the affected resource
            changes: List of field changes [{field, before, after}]
            actor_type: Type of actor ("user", "service", "system", "api_key")
            event_metadata: Additional context
        """
        ctx = get_audit_context()

        event = AuditEventORM(
            actor_id=self._user_context.user_id,
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

        event = await self._repository.insert(event)

        # Forward to enterprise audit sink if registered
        sink_factory = ExtensionRegistry.get_factory("audit_sink")
        if sink_factory:
            try:
                sink = sink_factory()
                await sink.emit(event.to_dict())
            except Exception:
                logger.warning("Failed to forward audit event to enterprise sink")

        return event
