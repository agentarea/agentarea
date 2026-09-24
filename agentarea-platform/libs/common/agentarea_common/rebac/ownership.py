"""Ownership grants for graph-governed resources.

A resource that reaches the database without its graph tuples is invisible to
the authorization model: ``OpenFGAPermissionService`` fails closed, so its own
creator is refused on it. That is not hypothetical -- agents and skills created
through the platform toolsets had exactly this shape, because the grant lived
at the HTTP route while the toolsets called the same service directly.

So the grant belongs where rows are created, not where requests arrive:
``WorkspaceScopedRepository.create`` calls this for any model that declares
``__graph_resource__``. Every creation path -- route, platform toolset, worker,
bundle install -- gets it by construction, and a new one cannot forget.
"""

from __future__ import annotations

import logging
from uuid import UUID

from .keto_client import KetoClient, KetoError, KetoUnavailableError
from .models import RelationTuple
from .openfga_client import OpenFGAClient, OpenFGAError, OpenFGAUnavailableError

logger = logging.getLogger(__name__)

GraphClient = KetoClient | OpenFGAClient
_GRAPH_WRITE_ERRORS = (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError)

#: Bits granted to a creator. The model uses INDEPENDENT permission bits with no
#: roll-up, so ``manager`` alone would confer neither read nor write.
OWNER_RELATIONS = ("reader", "writer", "manager")


class ResourceOwnershipError(RuntimeError):
    """The graph could not record ownership, so the caller must not proceed.

    Raised rather than swallowed: a resource whose ownership was not recorded is
    unreachable to everyone, including the person who just created it. Callers
    surface this as a 503 -- the write is retryable and the grant is idempotent.
    """


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


def resolve_graph_client() -> tuple[GraphClient, str] | None:
    """Return (client, backend name) for the configured graph.

    ``None`` means no graph backend is configured at all, which the application
    refuses to start with -- see ``apps/api/main.py``. Reaching it from a
    repository would mean the process started without one, so callers treat it
    as a misconfiguration rather than as permission to skip the grant.
    """
    from agentarea_common.config import get_settings
    from agentarea_common.di.container import get_container

    backend = get_settings().access_control.BACKEND
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
    except ValueError as exc:
        raise ResourceOwnershipError(
            f"{backend_name} is the configured access-control backend but no client "
            "is registered; ownership of new resources cannot be recorded"
        ) from exc


async def write_tuple_idempotent(
    client: GraphClient, backend: str, relationship: RelationTuple
) -> None:
    try:
        await client.write_tuple(relationship)
    except _GRAPH_WRITE_ERRORS as exc:
        if _is_existing_tuple_error(exc):
            logger.debug("Relation already exists in %s: %s", backend, relationship)
            return
        logger.exception("Failed to write relation in %s: %s", backend, relationship)
        raise ResourceOwnershipError(f"{backend} grant write failed") from exc


async def grant_resource_owner(
    *,
    resource_id: UUID | str,
    workspace_id: str,
    user_id: str,
) -> None:
    """Attach a newly created resource to its workspace root project and own it.

    Writes ``resource:<id>#project@project:<ws>-root`` plus direct
    reader/writer/manager for the creator. A workspace admin additionally reaches
    the resource through the workspace -> root-project -> resource cascade.
    Idempotent, so re-asserting on a later write is harmless.
    """
    resolved = resolve_graph_client()
    if resolved is None:
        return
    client, backend = resolved
    resource_obj = str(resource_id)

    await write_tuple_idempotent(
        client,
        backend,
        RelationTuple(
            namespace="resource",
            object=resource_obj,
            relation="project",
            subject_id=f"project:{root_project_id(workspace_id)}",
        ),
    )
    for relation in OWNER_RELATIONS:
        await write_tuple_idempotent(
            client,
            backend,
            RelationTuple(
                namespace="resource",
                object=resource_obj,
                relation=relation,
                subject_id=f"User:{user_id}",
            ),
        )


def graph_governed_models() -> list[type]:
    """Every mapped model that declares ``__graph_resource__``.

    Derived from the SQLAlchemy registry rather than from a list, so the
    reconcile script below cannot drift from what the repository actually
    grants: marking a new model governs it in both places at once. Callers must
    import the model modules first -- an unimported model is not mapped.
    """
    from agentarea_common.base.models import BaseModel

    seen: dict[str, type] = {}
    for mapper in BaseModel.registry.mappers:
        model = mapper.class_
        if getattr(model, "__graph_resource__", False):
            seen[model.__tablename__] = model
    return [seen[name] for name in sorted(seen)]
