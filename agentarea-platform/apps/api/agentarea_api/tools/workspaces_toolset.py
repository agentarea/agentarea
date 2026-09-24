"""WorkspacesToolset — find and create the workspaces a caller can act in.

Served only on the bare ``/mcp`` mount, which spans workspaces: its other tools
take a ``workspace`` argument, and this is where a caller learns the values.
The toolset itself acts on no single workspace, so it opts out of that argument.
"""

import json

from agentarea_agents_sdk.mcp_server.auth import get_mcp_user_context
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.config import get_database, get_settings

from agentarea_api.api.v1.workspaces import get_workspace_service, list_reachable_workspaces


def _describe(workspace) -> dict:
    api_base = get_settings().app.API_BASE_URL.rstrip("/")
    return {
        "id": workspace.id,
        "slug": workspace.slug,
        "name": workspace.name,
        "owner_user_id": workspace.owner_user_id,
        "mcp_url": f"{api_base}/mcp/w/{workspace.slug}",
    }


@toolset(
    namespace="agentarea/workspaces",
    display_name="Workspaces",
    description="List the workspaces you can reach and create new ones.",
    category="platform",
    plane="govern",
)
class WorkspacesToolset(Toolset):
    """List the workspaces you can reach and create new ones."""

    workspace_scoped = False

    @tool_method(effect="read")
    async def list(self, query: str | None = None) -> str:
        """List the workspaces you can reach, optionally filtered by a name or slug substring.

        Pass a returned ``slug`` as the ``workspace`` argument of other tools.
        """
        user_ctx = get_mcp_user_context()
        async with get_database().async_session_factory() as session:
            workspaces = await list_reachable_workspaces(
                user_ctx, get_workspace_service(session, user_ctx)
            )
        if query:
            needle = query.strip().lower()
            workspaces = [
                w for w in workspaces if needle in w.slug.lower() or needle in w.name.lower()
            ]
        return json.dumps([_describe(w) for w in workspaces])

    @tool_method(effect="write")
    async def create(self, name: str) -> str:
        """Create a shared workspace owned by you and return it."""
        name = name.strip()
        if not name:
            raise ValueError("Workspace name must not be empty")
        if len(name) > 255:
            raise ValueError("Workspace name must be at most 255 characters")
        user_ctx = get_mcp_user_context()
        async with get_database().async_session_factory() as session:
            workspace = await get_workspace_service(session, user_ctx).create_shared(
                owner_user_id=user_ctx.user_id, name=name
            )
        return json.dumps(_describe(workspace))
