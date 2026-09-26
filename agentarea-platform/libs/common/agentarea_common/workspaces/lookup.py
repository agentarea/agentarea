"""Load a workspace row by id or slug, outside any request transaction."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentarea_common.auth.context import UserContext

    from .models import Workspace


async def load_workspace(
    *, workspace_id: str | None = None, slug: str | None = None
) -> Workspace | None:
    """The workspace named by exactly one of ``workspace_id`` or ``slug``.

    Database errors propagate: a failed lookup is not a missing workspace.
    """
    from agentarea_common.config.database import get_database

    from .repository import WorkspaceRepository

    if (workspace_id is None) == (slug is None):
        raise ValueError("name a workspace by exactly one of workspace_id or slug")
    async with get_database().async_session_factory() as session:
        repository = WorkspaceRepository(session)
        if workspace_id is not None:
            return await repository.get(workspace_id)
        return await repository.get_by_slug(slug)  # type: ignore[arg-type]


async def workspace_slug_for(workspace_id: str) -> str:
    """The URL slug of ``workspace_id``; raises when no such workspace exists."""
    workspace = await load_workspace(workspace_id=workspace_id)
    if workspace is None:
        raise LookupError(f"Workspace {workspace_id} does not exist")
    return workspace.slug


async def workspace_api_prefix(user_context: UserContext) -> str:
    """``/v1/workspaces/{slug}`` for the workspace ``user_context`` acts in.

    Contexts minted outside HTTP (worker, A2A) name their workspace by id only;
    its slug is read from the workspace row.
    """
    slug = user_context.workspace_slug or await workspace_slug_for(user_context.workspace_id)
    return f"/v1/workspaces/{slug}"
