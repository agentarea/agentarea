"""AuditToolset — read-only audit log access."""

import json
from datetime import datetime
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires_workspace_admin
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
    @requires_workspace_admin()
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
            from agentarea_common.audit.repository import AuditRepository, UnknownAuditCursorError

            # The page the repository actually returns, so a full page is
            # recognised as one when next_cursor is decided below.
            limit = max(1, min(limit, 100))
            repo = AuditRepository(session)
            try:
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
            except UnknownAuditCursorError as error:
                return json.dumps({"error": str(error)})
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
                    "next_cursor": str(events[-1].id) if len(events) == limit else None,
                },
                default=str,
            )
