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

from .models import RelationQuery, RelationTuple
from .openfga_client import OpenFGAClient, OpenFGAError

logger = logging.getLogger(__name__)

#: Bits granted to a creator. The model uses INDEPENDENT permission bits with no
#: roll-up, so ``manager`` alone would confer neither read nor write.
OWNER_RELATIONS = ("reader", "writer", "manager")

#: Who may run an agent. Nothing implies it -- not managing the agent, not
#: administering its workspace -- so a creator is granted it explicitly, and
#: everyone else only when someone with ``can_manage`` grants it.
INVOKER_RELATION = "invoker"


def owner_relations(model: type) -> tuple[str, ...]:
    """The relations a creator of ``model`` rows is granted.

    A model narrows or widens the default by declaring
    ``__graph_owner_relations__``; an agent adds ``invoker``.
    """
    return tuple(getattr(model, "__graph_owner_relations__", OWNER_RELATIONS))


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


def _is_missing_tuple_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "does not exist" in message or "did not exist" in message


def resolve_graph_client() -> OpenFGAClient:
    """Return the registered OpenFGA client.

    The application refuses to start without one -- see ``apps/api/main.py`` --
    so its absence here is a misconfiguration, not permission to skip the grant.
    """
    from agentarea_common.di.container import get_container

    try:
        return get_container().get(OpenFGAClient)
    except ValueError as exc:
        raise ResourceOwnershipError(
            "no OpenFGA client is registered; ownership of new resources cannot be recorded"
        ) from exc


async def write_tuple_idempotent(client: OpenFGAClient, relationship: RelationTuple) -> bool:
    """Write ``relationship``; one that is already there is not an error.

    Returns whether the graph changed: ``False`` when the tuple already existed.
    """
    try:
        await client.write_tuple(relationship)
    except OpenFGAError as exc:
        if _is_existing_tuple_error(exc):
            logger.debug("Relation already exists: %s", relationship)
            return False
        logger.exception("Failed to write relation: %s", relationship)
        raise ResourceOwnershipError("OpenFGA grant write failed") from exc
    return True


async def delete_tuple_idempotent(client: OpenFGAClient, relationship: RelationTuple) -> bool:
    """Delete ``relationship``; one that is already gone is not an error.

    Returns whether the graph changed: ``False`` when there was nothing to delete.
    """
    try:
        await client.delete_tuple(relationship)
    except OpenFGAError as exc:
        if _is_missing_tuple_error(exc):
            logger.debug("Relation already absent: %s", relationship)
            return False
        logger.exception("Failed to delete relation: %s", relationship)
        raise ResourceOwnershipError("OpenFGA grant delete failed") from exc
    return True


async def grant_resource_owner(
    *,
    resource_id: UUID | str,
    workspace_id: str,
    user_id: str,
    relations: tuple[str, ...] = OWNER_RELATIONS,
) -> None:
    """Attach a newly created resource to its workspace root project and own it.

    Writes ``resource:<id>#project@project:<ws>-root`` plus direct
    reader/writer/manager for the creator. A workspace admin additionally reaches
    the resource through the workspace -> root-project -> resource cascade.
    Idempotent, so re-asserting on a later write is harmless.
    """
    client = resolve_graph_client()
    resource_obj = str(resource_id)

    await write_tuple_idempotent(
        client,
        RelationTuple(
            namespace="resource",
            object=resource_obj,
            relation="project",
            subject_id=f"project:{root_project_id(workspace_id)}",
        ),
    )
    for relation in relations:
        await write_tuple_idempotent(
            client,
            RelationTuple(
                namespace="resource",
                object=resource_obj,
                relation=relation,
                subject_id=f"User:{user_id}",
            ),
        )


async def revoke_resource(resource_id: UUID | str) -> None:
    """Delete every tuple on ``resource:<id>`` once its row is gone.

    Reads one object, so the cost is that resource's own tuples. Without this
    the store keeps the grants of every row ever deleted.
    """
    client = resolve_graph_client()
    tuples = await client.query_all_tuples(
        RelationQuery(namespace="resource", object=str(resource_id))
    )
    for relationship in tuples:
        await client.delete_tuple(relationship)


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
