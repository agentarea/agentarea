"""WorkspacesToolset — find, create and update the workspaces a caller can act in.

Served only on the bare ``/mcp`` mount, which spans workspaces: its other tools
take a ``workspace`` argument, and this is where a caller learns the values.
The toolset itself acts on no single workspace, so it opts out of that argument.
"""

import json
from dataclasses import replace

from agentarea_agents_sdk.mcp_server.auth import get_mcp_user_context
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import enforced_in_handler, unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.artifacts import ArtifactService, InvalidArtifactPathError
from agentarea_common.auth.authorization import assert_workspace_admin
from agentarea_common.auth.dependencies import ensure_not_workspace_bound
from agentarea_common.config import get_database, get_settings
from agentarea_common.workspaces import WorkspaceRepository
from agentarea_common.workspaces.logo import (
    LOGO_MAX_BYTES,
    LogoTooLargeError,
    WorkspaceLogoError,
    WorkspaceLogoService,
    WorkspaceLogoStore,
)
from fastapi import HTTPException

from agentarea_api.api.v1.workspaces import (
    WorkspaceResponse,
    describe_workspace,
    describe_workspaces,
    get_workspace_service,
    list_reachable_workspaces,
)


def _describe(workspace: WorkspaceResponse) -> dict:
    api_base = get_settings().app.API_URL.rstrip("/")
    return {**workspace.model_dump(), "mcp_url": f"{api_base}/mcp/w/{workspace.slug}"}


@toolset(
    namespace="agentarea/workspaces",
    display_name="Workspaces",
    description="List the workspaces you can reach, create new ones, and update their settings.",
    category="platform",
    plane="govern",
)
class WorkspacesToolset(Toolset):
    """List the workspaces you can reach, create new ones, and update their settings."""

    workspace_scoped = False

    @tool_method(effect="read")
    @unrestricted("returns only the workspaces the caller already reaches, as GET /v1/workspaces")
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
        return json.dumps([_describe(w) for w in await describe_workspaces(user_ctx, workspaces)])

    @tool_method(effect="write")
    @unrestricted("anyone may create a workspace; they become its owner, as POST /v1/workspaces")
    async def create(self, name: str) -> str:
        """Create a shared workspace owned by you and return it."""
        name = name.strip()
        if not name:
            raise ValueError("Workspace name must not be empty")
        if len(name) > 255:
            raise ValueError("Workspace name must be at most 255 characters")
        user_ctx = get_mcp_user_context()
        ensure_not_workspace_bound(user_ctx)
        async with get_database().async_session_factory() as session:
            workspace = await get_workspace_service(session, user_ctx).create_shared(
                owner_user_id=user_ctx.user_id, name=name
            )
        # Access was resolved before this row existed; its creator owns it.
        creator = replace(
            user_ctx, admin_workspaces=[*(user_ctx.admin_workspaces or []), workspace.id]
        )
        [described] = await describe_workspaces(creator, [workspace])
        return json.dumps(_describe(described))

    @tool_method(effect="write")
    @enforced_in_handler("admin of the named workspace, as PUT and DELETE .../logo require")
    async def update(
        self, workspace: str, logo_path: str | None = None, clear_logo: bool = False
    ) -> str:
        """Update a workspace's settings and return it; only the settings passed change.

        ``workspace`` is a ``slug`` from ``list``. To set the logo, upload the
        image into that workspace's files first (``agentarea/workspace_files``
        ``upload_urls``, then PUT the bytes to the returned URL), and pass its
        path as ``logo_path``. The image must be PNG, JPEG or WebP and at most
        1 MB. ``clear_logo=True`` removes the logo instead.
        """
        if logo_path is not None and clear_logo:
            return json.dumps({"error": "Pass either logo_path or clear_logo, not both"})
        if logo_path is None and not clear_logo:
            return json.dumps({"error": "Nothing to update: pass logo_path or clear_logo"})
        principal = get_mcp_user_context()
        async with get_database().async_session_factory() as session:
            reachable = await list_reachable_workspaces(
                principal, get_workspace_service(session, principal)
            )
            target = next((w for w in reachable if workspace in (w.slug, w.id)), None)
            if target is None:
                return json.dumps({"error": f"No accessible workspace '{workspace}'"})
            context = replace(
                principal,
                accessible_workspaces=[*(principal.accessible_workspaces or []), target.id],
            ).enter(target.id, target.slug)
            try:
                await assert_workspace_admin(context)
            except HTTPException as exc:
                return json.dumps({"error": exc.detail})

            logos = WorkspaceLogoStore()
            service = WorkspaceLogoService(session, WorkspaceRepository(session), logos)
            try:
                if logo_path is None:
                    updated = await service.remove(target.id)
                else:
                    files = ArtifactService()
                    try:
                        head = await files.head(target.id, logo_path)
                    except InvalidArtifactPathError as exc:
                        return json.dumps({"error": str(exc)})
                    if head is None:
                        return json.dumps({"error": "File not found"})
                    if head["size"] > LOGO_MAX_BYTES:
                        raise LogoTooLargeError
                    data, _content_type = await files.get(target.id, logo_path)
                    updated = await service.set(target.id, data)
            except WorkspaceLogoError as exc:
                return json.dumps({"error": str(exc)})
            return json.dumps(_describe(await describe_workspace(context, updated, logos)))
