"""AuditToolset — read-only audit log access."""

import json
from datetime import datetime
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset

from .base import platform_read_context


@toolset(
    namespace="agentarea/audit",
    display_name="Audit Log",
    description="Inspect workspace audit log entries.",
    category="platform",
    plane="observe",
)
class AuditToolset(Toolset):
    """Query the workspace audit log (read-only)."""

    @tool_method(effect="read")
    async def list(
        self,
        action: str = "",
        actor_id: str = "",
        resource_type: str = "",
        resource_id: str = "",
        since: str = "",
        until: str = "",
        cursor: str = "",
        limit: int = 50,
    ) -> str:
        """List audit events. Time fields use ISO 8601. Returns next_cursor for pagination."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            from agentarea_common.audit.repository import AuditRepository

            repo = AuditRepository(session)
            events = await repo.query(
                workspace_id=user_ctx.workspace_id,
                action=action or None,
                actor_id=actor_id or None,
                resource_type=resource_type or None,
                resource_id=resource_id or None,
                since=datetime.fromisoformat(since) if since else None,
                until=datetime.fromisoformat(until) if until else None,
                cursor=UUID(cursor) if cursor else None,
                limit=limit,
            )
            items = [
                {
                    "id": str(e.id),
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "actor_id": e.actor_id,
                    "actor_type": e.actor_type,
                    "action": e.action,
                    "resource_type": e.resource_type,
                    "resource_id": e.resource_id,
                    "request_id": e.request_id,
                }
                for e in events
            ]
            return json.dumps(
                {
                    "events": items,
                    "next_cursor": str(events[-1].id) if events else None,
                },
                default=str,
            )
