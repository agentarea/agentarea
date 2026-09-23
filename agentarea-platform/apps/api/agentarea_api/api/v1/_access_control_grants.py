"""Graph grants for resources the API creates, and for fresh workspaces.

The ownership grant itself lives in ``agentarea_common.rebac.ownership`` and is
written by ``WorkspaceScopedRepository.create``, so every creation path gets it
-- including the platform toolsets in ``libs/agents``, which cannot import this
module. What remains here is the HTTP translation (a failed grant is a 503, not
a 500) and the workspace seed, which has no row of its own to hang off.
"""

from __future__ import annotations

from uuid import UUID

from agentarea_common.rebac import (
    RelationTuple,
    ResourceOwnershipError,
    resolve_graph_client,
    root_project_id,
    write_tuple_idempotent,
)
from agentarea_common.rebac import grant_resource_owner as _grant_resource_owner
from fastapi import HTTPException

__all__ = ["grant_resource_owner", "root_project_id", "seed_workspace"]


def _as_http(exc: ResourceOwnershipError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


async def grant_resource_owner(
    *,
    resource_id: UUID | str,
    workspace_id: str,
    user_id: str,
) -> None:
    """Assert ownership from a request handler, surfacing failure as a 503.

    Repository-created rows are already granted; this stays for the paths that
    materialize a resource some other way (catalog install, copy-on-write fork)
    and for re-asserting ownership, which is idempotent.
    """
    try:
        await _grant_resource_owner(
            resource_id=resource_id, workspace_id=workspace_id, user_id=user_id
        )
    except ResourceOwnershipError as exc:
        raise _as_http(exc) from exc


async def seed_workspace(*, workspace_id: str, creator_user_id: str) -> None:
    """Make a fresh workspace usable out of the box (idempotent).

    Writes the graph tuples every workspace needs so no manual setup is required:
      - ``Workspace:<ws>#members@User:<creator>`` (switcher + membership defaults)
      - ``Workspace:<ws>#admin@User:<creator>`` (full-access escape hatch)
      - ``project:<ws>-root#workspace@Workspace:<ws>`` (the default root project)

    The baseline governance policy row is provisioned separately by the workspace
    creation hook (``provision_default_policies``), keeping this graph seed free of
    a dependency on the governance domain.
    """
    try:
        resolved = resolve_graph_client()
    except ResourceOwnershipError as exc:
        raise _as_http(exc) from exc
    if resolved is None:
        return
    client, backend = resolved

    tuples = (
        RelationTuple(
            namespace="Workspace",
            object=workspace_id,
            relation="members",
            subject_id=f"User:{creator_user_id}",
        ),
        RelationTuple(
            namespace="Workspace",
            object=workspace_id,
            relation="admin",
            subject_id=f"User:{creator_user_id}",
        ),
        RelationTuple(
            namespace="project",
            object=root_project_id(workspace_id),
            relation="workspace",
            subject_id=f"Workspace:{workspace_id}",
        ),
    )
    try:
        for relationship in tuples:
            await write_tuple_idempotent(client, backend, relationship)
    except ResourceOwnershipError as exc:
        raise _as_http(exc) from exc
