"""AuditToolset — read-only audit log access."""

import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires_workspace_admin
from agentarea_agents_sdk.tools.tool_definition import toolset
from pydantic import BaseModel, Field

from .base import platform_read_context


class AuditEventOutput(BaseModel):
    id: str = Field(description="Audit event id.")
    created_at: str | None = Field(description="When the action happened, ISO 8601.")
    actor_id: str = Field(description="Who acted: a user id, service or API key id.")
    actor_type: str = Field(description="Kind of actor: user, service, system or api_key.")
    action: str = Field(description="Hierarchical action name, e.g. agent.create.")
    resource_type: str = Field(description="Type of the resource acted on, e.g. agent.")
    resource_id: str | None = Field(description="Id of the resource acted on, when there is one.")
    request_id: str | None = Field(description="Id of the request that made the change.")


class AuditEventsPage(BaseModel):
    events: list[AuditEventOutput] = Field(description="Matching events, newest first.")
    next_cursor: str | None = Field(
        description="Pass as `cursor` for the next page; null when this was the last page."
    )


@toolset(
    namespace="agentarea/audit",
    display_name="Audit Log",
    description="Inspect workspace audit log entries.",
    category="platform",
    plane="observe",
)
class AuditToolset(Toolset):
    """Query the workspace audit log (read-only)."""

    open_world = False

    @tool_method(display_name="List audit events", effect="read", output=AuditEventsPage)
    @requires_workspace_admin()
    async def list(
        self,
        action: Annotated[
            str,
            Field(description="Exact action name to match, e.g. agent.create; empty for any."),
        ] = "",
        actor_id: Annotated[
            str, Field(description="Only events by this actor id, e.g. a user id; empty for any.")
        ] = "",
        resource_type: Annotated[
            str, Field(description="Only events on this resource type, e.g. agent; empty for any.")
        ] = "",
        resource_id: Annotated[
            str, Field(description="Only events on this resource id; empty for any.")
        ] = "",
        since: Annotated[
            str,
            Field(
                description="Earliest event time, ISO 8601, e.g. 2026-09-01T00:00:00+00:00; "
                "empty for no lower bound."
            ),
        ] = "",
        until: Annotated[
            str, Field(description="Latest event time, ISO 8601; empty for no upper bound.")
        ] = "",
        cursor: Annotated[
            str,
            Field(description="`next_cursor` from the previous page; empty for the first page."),
        ] = "",
        limit: Annotated[
            int, Field(description="Events per page, 1-100; larger values are capped at 100.")
        ] = 50,
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
                raise ToolError(str(error)) from error
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
