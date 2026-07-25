"""Small helpers for keeping resource CRUD aligned with graph permissions."""

from __future__ import annotations

import logging
from uuid import UUID

from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.rebac import (
    KetoClient,
    KetoError,
    KetoUnavailableError,
    OpenFGAClient,
    OpenFGAError,
    OpenFGAUnavailableError,
    RelationTuple,
)
from fastapi import HTTPException

logger = logging.getLogger(__name__)

GraphClient = KetoClient | OpenFGAClient
_GRAPH_WRITE_ERRORS = (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError)


def root_project_id(workspace_id: str) -> str:
    """Object id of the default root project for a workspace.

    Every workspace-level resource attaches to ``project:<ws>-root``; because a
    project rolls ``admin from workspace`` into all three bits, a workspace admin
    manages the root project and everything under it.
    """
    return f"{workspace_id}-root"


def _is_existing_tuple_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "already exists" in message or "tuple to be written already existed" in message


def _resolve_graph_client() -> tuple[GraphClient, str] | None:
    """Return (client, backend_name) for the configured graph, or None when disabled."""
    settings = get_settings()
    backend = settings.access_control.ACCESS_CONTROL_BACKEND
    if backend == "openfga":
        client_type: type[GraphClient] = OpenFGAClient
        backend_name = "OpenFGA"
    elif backend == "keto":
        client_type = KetoClient
        backend_name = "Keto"
    else:
        return None
    try:
        return get_container().get(client_type), backend_name
    except ValueError:
        logger.exception("%s is enabled but client is not registered", backend_name)
        raise HTTPException(
            status_code=503,
            detail=f"{backend_name} grant writer is unavailable",
        ) from None


async def _write_idempotent(client: GraphClient, backend: str, relationship: RelationTuple) -> None:
    try:
        await client.write_tuple(relationship)
    except _GRAPH_WRITE_ERRORS as exc:
        if _is_existing_tuple_error(exc):
            logger.debug("Relation already exists in %s: %s", backend, relationship)
            return
        logger.exception("Failed to write relation in %s: %s", backend, relationship)
        raise HTTPException(
            status_code=503,
            detail=f"{backend} grant write failed",
        ) from exc


async def grant_resource_owner(
    *,
    resource_id: UUID | str,
    workspace_id: str,
    user_id: str,
) -> None:
    """Attach a newly created resource to its workspace root project and own it.

    Writes ``resource:<id>#project@project:<ws>-root`` plus direct
    reader/writer/manager for the creator. The three bits are granted explicitly
    because the model uses INDEPENDENT permission bits (no roll-up): ``manager``
    alone would not confer read/write. A workspace admin additionally reaches the
    resource through the workspace -> root-project -> resource cascade.
    """
    resolved = _resolve_graph_client()
    if resolved is None:
        return
    client, backend = resolved
    resource_obj = str(resource_id)

    await _write_idempotent(
        client,
        backend,
        RelationTuple(
            namespace="resource",
            object=resource_obj,
            relation="project",
            subject_id=f"project:{root_project_id(workspace_id)}",
        ),
    )
    for relation in ("reader", "writer", "manager"):
        await _write_idempotent(
            client,
            backend,
            RelationTuple(
                namespace="resource",
                object=resource_obj,
                relation=relation,
                subject_id=f"User:{user_id}",
            ),
        )


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
    resolved = _resolve_graph_client()
    if resolved is None:
        return
    client, backend = resolved

    await _write_idempotent(
        client,
        backend,
        RelationTuple(
            namespace="Workspace",
            object=workspace_id,
            relation="members",
            subject_id=f"User:{creator_user_id}",
        ),
    )
    await _write_idempotent(
        client,
        backend,
        RelationTuple(
            namespace="Workspace",
            object=workspace_id,
            relation="admin",
            subject_id=f"User:{creator_user_id}",
        ),
    )
    await _write_idempotent(
        client,
        backend,
        RelationTuple(
            namespace="project",
            object=root_project_id(workspace_id),
            relation="workspace",
            subject_id=f"Workspace:{workspace_id}",
        ),
    )
