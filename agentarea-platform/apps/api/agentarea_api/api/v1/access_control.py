"""Access-control relationship explorer API.

Surfaces the authorization relationship graph that the frontend access explorer
renders: nodes (agents, skill collections, MCP servers), access relationships,
permission checks, and path resolution.

Ownership is modelled on the converged ``resource``/``project``/``role`` graph:
agents, skills, MCP servers, and clients are all ``resource:<uuid>`` objects with
direct ``reader``/``writer``/``manager`` grants (see ``_access_control_grants``).
The explorer reads that model and maps each ``resource:<uuid>`` back onto the
DB-backed node it represents. The retired per-type namespaces (``Skill``,
``SkillCollection``, ``MCPServer``, and ``Agent`` ownership) are no longer part
of the graph.

The graph backend is OpenFGA.
"""

import asyncio
import logging
from collections.abc import Collection
from typing import Annotated, Any, Literal
from uuid import UUID

from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.collection_repository import (
    SkillCollectionRepository,
)
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_common.audit import AuditService
from agentarea_common.auth import (
    UserContext,
    UserContextDep,
)
from agentarea_common.auth import (
    assert_workspace_admin as _assert_workspace_admin,
)
from agentarea_common.auth.route_authz import enforced_in_handler
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_db_session
from agentarea_common.di.container import get_container
from agentarea_common.rebac import (
    OpenFGAClient,
    OpenFGAError,
    RelationQuery,
    RelationTuple,
    write_tuple_idempotent,
)
from agentarea_common.workspaces.models import Workspace, WorkspaceMembership
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["access-control"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session, scope="function")]

# Stable colour palettes per node kind. Index into them by enumeration order so
# the same workspace always renders the same colours.
_COLORS: dict[str, list[str]] = {
    "agent": ["#6366f1", "#8b5cf6", "#a855f7", "#7c3aed", "#4f46e5"],
    "collection": ["#0ea5e9", "#06b6d4", "#0891b2", "#0284c7", "#22d3ee"],
    "mcp": ["#10b981", "#14b8a6", "#059669", "#16a34a", "#34d399"],
    "skill": ["#f59e0b", "#f97316", "#fbbf24", "#ea580c", "#fb923c"],
}

# The ``resource`` model exposes three independent permission bits granted
# directly to a subject. Map them onto the explorer's grant vocabulary and a
# highest-wins ordering.
_GRANT_LABEL = {"reader": "user", "writer": "editor", "manager": "owner"}
_GRANT_RANK = {"reader": 1, "writer": 2, "manager": 3}

# Verb the frontend resolves per resource kind, and the resource bit it maps to.
_VERB_BY_KIND = {
    "skill": "use",
    "collection": "use",
    "mcp": "connect",
    "agent": "operate",
}
_VERB_TO_BIT = {
    "use": "can_read",
    "view": "can_read",
    "read": "can_read",
    "operate": "can_read",
    "connect": "can_read",
    "execute": "can_read",
    "configure": "can_write",
    "edit": "can_write",
    "write": "can_write",
    "manage": "can_manage",
    "own": "can_manage",
    "delete": "can_manage",
}
# Legacy per-type grant relations the explorer used to write, mapped onto the
# ``resource`` grant relation they now correspond to.
_LEGACY_RELATION_TO_GRANT = {
    "viewers": "reader",
    "connectors": "reader",
    "editors": "writer",
    "owners": "manager",
    "operators": "manager",
    "reader": "reader",
    "writer": "writer",
    "manager": "manager",
}


def get_graph_client() -> OpenFGAClient:
    """Resolve the shared OpenFGA client."""
    try:
        return get_container().get(OpenFGAClient)
    except ValueError:
        settings = get_settings()
        return OpenFGAClient(
            api_url=settings.openfga.URL,
            store_id=settings.openfga.STORE_ID,
            authorization_model_id=settings.openfga.MODEL_ID,
            timeout_seconds=settings.openfga.TIMEOUT.total_seconds(),
            api_token=settings.openfga.API_TOKEN or None,
        )


def _color(kind: str, index: int) -> str:
    palette = _COLORS[kind]
    return palette[index % len(palette)]


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class GraphNode(BaseModel):
    id: str
    kind: Literal["agent", "collection", "mcp"]
    name: str
    subtitle: str
    color: str
    count: int | None = None


class GraphEdge(BaseModel):
    from_: str
    to: str
    relation: str

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        data = super().model_dump(**kwargs)
        data["from"] = data.pop("from_")
        return data


class GraphStats(BaseModel):
    governed_skill_count: int
    rule_count: int
    direct_exception_count: int


class GraphResponse(BaseModel):
    enabled: bool
    nodes: list[GraphNode]
    edges: list[dict]
    stats: GraphStats


class RelationshipItem(BaseModel):
    namespace: str
    object: str
    object_name: str
    relation: str
    subject: str
    subject_kind: Literal["agent", "user", "workspace"]
    subject_name: str
    fanout: int | None = None
    direct: bool


class RelationshipsResponse(BaseModel):
    relationships: list[RelationshipItem]
    count: int


class SubjectSetBody(BaseModel):
    namespace: str
    object: str
    relation: str


class RelationshipWriteRequest(BaseModel):
    namespace: str
    object: str
    relation: str
    subject_id: str | None = None
    subject_set: SubjectSetBody | None = None


class CheckRequest(BaseModel):
    namespace: str
    object: str
    relation: str
    subject_id: str


class CheckResponse(BaseModel):
    allowed: bool


class ResolveRequest(BaseModel):
    subject_id: str
    resource_kind: Literal["skill", "collection", "mcp", "agent"]
    resource_id: str


class ResolveHop(BaseModel):
    id: str
    name: str
    kind: str
    color: str


class ResolvePath(BaseModel):
    relation: str
    hops: list[ResolveHop]
    rels: list[str]


class ResolveResponse(BaseModel):
    allowed: bool
    effective_relation: str | None
    verb: str
    paths: list[ResolvePath]


class SyncResponse(BaseModel):
    written: int
    collections: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Point reads of one object each; bounded so a large workspace does not open
# hundreds of concurrent requests to the graph backend.
_GRAPH_READ_CONCURRENCY = 16


async def _resource_tuples(
    client: OpenFGAClient, object_ids: Collection[str]
) -> list[RelationTuple]:
    """The ``resource`` grant tuples on ``object_ids``, tolerating graph outages.

    Read object by object: an unfiltered read of the namespace walks every
    tenant's tuples page by page, and once the store holds a few thousand it
    runs past OpenFGA's deadline and the explorer returns 500.
    """
    semaphore = asyncio.Semaphore(_GRAPH_READ_CONCURRENCY)

    async def read(object_id: str) -> list[RelationTuple]:
        async with semaphore:
            return await client.query_all_tuples(
                RelationQuery(namespace="resource", object=object_id)
            )

    try:
        batches = await asyncio.gather(*(read(object_id) for object_id in sorted(set(object_ids))))
    except OpenFGAError:
        logger.exception("Failed to query resource relationships from graph backend")
        return []
    return [tuple_ for batch in batches for tuple_ in batch]


# Frontend node/subject namespaces are workspace-scoped by their DB repository.
# These are DB lookups (not graph types) used to validate that an object the
# admin references belongs to the caller's workspace.
_NAMESPACE_REPOS: dict[str, type] = {
    "Agent": AgentRepository,
    "MCPServer": MCPServerRepository,
    "Skill": SkillRepository,
    "SkillCollection": SkillCollectionRepository,
}
_READABLE_NAMESPACES = set(_NAMESPACE_REPOS)
# Frontend namespace -> the node kind it maps onto, for relationship grouping.
_NAMESPACE_KIND = {
    "Agent": "agent",
    "SkillCollection": "collection",
    "MCPServer": "mcp",
    "Skill": "skill",
}


async def _workspace_member_ids(
    user_context: UserContext,
    db_session: AsyncSession,
) -> set[str]:
    owner_query = select(Workspace.owner_user_id).where(Workspace.id == user_context.workspace_id)
    owner_user_id = (await db_session.execute(owner_query)).scalar_one_or_none()
    member_query = select(WorkspaceMembership.user_id).where(
        WorkspaceMembership.workspace_id == user_context.workspace_id
    )
    member_ids = {str(row.user_id) for row in (await db_session.execute(member_query)).all()}
    member_ids.add(user_context.user_id)
    if owner_user_id:
        member_ids.add(str(owner_user_id))
    return member_ids


async def _assert_object_in_workspace(
    namespace: str,
    object_id: str,
    user_context: UserContext,
    db_session: AsyncSession,
) -> None:
    """Raise 403/422 if namespace:object_id does not belong to the caller's workspace."""
    repo_cls = _NAMESPACE_REPOS.get(namespace)
    if repo_cls is None:
        raise HTTPException(status_code=422, detail=f"Unsupported namespace: {namespace!r}")
    try:
        obj_uuid = UUID(object_id)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid object id: {object_id!r}") from None
    found = (
        await RepositoryFactory(db_session, user_context)
        .create_repository(repo_cls)
        .get_by_id(obj_uuid)
        is not None
    )
    if not found:
        raise HTTPException(
            status_code=403,
            detail=f"{namespace}:{object_id} not found in your workspace",
        )


async def _assert_subject_in_workspace(
    subject_id: str,
    user_context: UserContext,
    db_session: AsyncSession,
) -> None:
    if subject_id.startswith("Agent:"):
        await _assert_object_in_workspace(
            "Agent",
            subject_id.split(":", 1)[1],
            user_context,
            db_session,
        )
        return
    if subject_id.startswith("User:"):
        user_id = subject_id.split(":", 1)[1]
        if user_id not in await _workspace_member_ids(user_context, db_session):
            raise HTTPException(status_code=403, detail="Subject user is not in your workspace")
        return
    raise HTTPException(status_code=422, detail=f"Unsupported subject: {subject_id!r}")


def _to_resource_grant(payload: RelationshipWriteRequest) -> RelationTuple:
    """Translate an explorer write onto a ``resource`` grant tuple.

    Group grants (``subject_set``) are not part of the resource-ownership model;
    those flow through ``project``/``role`` and are rejected here.
    """
    if payload.subject_set is not None:
        raise HTTPException(
            status_code=422,
            detail="Group (subject_set) grants are managed via project/role, not the explorer",
        )
    if payload.subject_id is None:
        raise HTTPException(status_code=422, detail="subject_id is required")
    grant = _LEGACY_RELATION_TO_GRANT.get(payload.relation)
    if grant is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported relation for a resource grant: {payload.relation!r}",
        )
    return RelationTuple(
        namespace="resource",
        object=payload.object,
        relation=grant,
        subject_id=payload.subject_id,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/graph",
    response_model=GraphResponse,
    dependencies=[enforced_in_handler("workspace admin, asserted in the handler")],
)
async def get_graph(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> GraphResponse:
    """Return the full authorization graph for the current workspace."""
    await _assert_workspace_admin(user_context)
    factory = RepositoryFactory(db_session, user_context)
    agent_repo = factory.create_repository(AgentRepository)
    collection_repo = factory.create_repository(SkillCollectionRepository)
    mcp_repo = factory.create_repository(MCPServerRepository)

    agents = await agent_repo.list_all()
    collections = await collection_repo.list_all()
    mcp_servers = await mcp_repo.list_all()
    counts = await collection_repo.skill_counts()

    # All skills in the workspace (used for stats + resource-grant mapping).
    skill_count_query = select(Skill.id).where(Skill.workspace_id == user_context.workspace_id)
    skill_ids = {str(row.id) for row in (await db_session.execute(skill_count_query)).all()}
    governed_skill_count = len(skill_ids)

    nodes: list[GraphNode] = []
    agent_ids: set[str] = set()
    collection_ids: set[str] = set()
    mcp_ids: set[str] = set()
    # Map each resource uuid back onto the node id that represents it.
    node_id_by_uuid: dict[str, str] = {}

    for index, agent in enumerate(agents):
        node_id = f"Agent:{agent.id}"
        nodes.append(
            GraphNode(
                id=node_id,
                kind="agent",
                name=agent.name,
                subtitle="agent",
                color=_color("agent", index),
            )
        )
        agent_ids.add(str(agent.id))
        node_id_by_uuid[str(agent.id)] = node_id

    for index, collection in enumerate(collections):
        skills_in = counts.get(str(collection.id), 0)
        node_id = f"SkillCollection:{collection.id}"
        nodes.append(
            GraphNode(
                id=node_id,
                kind="collection",
                name=collection.name,
                subtitle=f"{skills_in} skills",
                color=_color("collection", index),
                count=skills_in,
            )
        )
        collection_ids.add(str(collection.id))
        node_id_by_uuid[str(collection.id)] = node_id

    for index, server in enumerate(mcp_servers):
        node_id = f"MCPServer:{server.id}"
        nodes.append(
            GraphNode(
                id=node_id,
                kind="mcp",
                name=server.name,
                subtitle="MCP server",
                color=_color("mcp", index),
            )
        )
        mcp_ids.add(str(server.id))
        node_id_by_uuid[str(server.id)] = node_id

    graph_client = get_graph_client()
    edges: list[dict] = []
    rule_count = 0
    direct_exception_count = 0

    for t in await _resource_tuples(graph_client, {*node_id_by_uuid, *skill_ids}):
        if t.relation not in _GRANT_LABEL:
            continue
        obj = str(t.object)
        subject_agent = (
            t.subject_id.split(":", 1)[1]
            if t.subject_id and t.subject_id.startswith("Agent:")
            else None
        )
        # Direct agent-to-skill grants are exceptions to collection defaults.
        if obj in skill_ids and subject_agent in agent_ids:
            direct_exception_count += 1
        target = node_id_by_uuid.get(obj)
        if target is None:
            continue
        rule_count += 1
        if subject_agent in agent_ids and f"Agent:{subject_agent}" != target:
            edges.append(
                GraphEdge(
                    from_=f"Agent:{subject_agent}",
                    to=target,
                    relation=_GRANT_LABEL[t.relation],
                ).model_dump()
            )

    stats = GraphStats(
        governed_skill_count=governed_skill_count,
        rule_count=rule_count,
        direct_exception_count=direct_exception_count,
    )
    return GraphResponse(
        enabled=True,
        nodes=nodes,
        edges=edges,
        stats=stats,
    )


@router.get(
    "/relationships",
    response_model=RelationshipsResponse,
    dependencies=[enforced_in_handler("workspace admin, asserted in the handler")],
)
async def list_relationships(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    namespace: str | None = None,
) -> RelationshipsResponse:
    """List resource-ownership grants enriched with display names.

    Grants live on ``resource:<uuid>`` objects; each is mapped back onto the DB
    entity (agent / skill collection / MCP server / skill) it represents. The
    optional ``namespace`` filter restricts results to one entity kind.
    """
    await _assert_workspace_admin(user_context)
    graph_client = get_graph_client()
    if namespace is not None and namespace not in _READABLE_NAMESPACES:
        raise HTTPException(status_code=422, detail=f"Unsupported namespace: {namespace!r}")

    factory = RepositoryFactory(db_session, user_context)
    agent_repo = factory.create_repository(AgentRepository)
    collection_repo = factory.create_repository(SkillCollectionRepository)
    mcp_repo = factory.create_repository(MCPServerRepository)

    agent_names = {str(a.id): a.name for a in await agent_repo.list_all()}
    collection_names = {str(c.id): c.name for c in await collection_repo.list_all()}
    mcp_names = {str(m.id): m.name for m in await mcp_repo.list_all()}
    skill_counts = await collection_repo.skill_counts()

    skill_names_query = select(Skill.id, Skill.name).where(
        Skill.workspace_id == user_context.workspace_id
    )
    skill_names = {
        str(row.id): row.name for row in (await db_session.execute(skill_names_query)).all()
    }

    # Which entity namespace each workspace uuid belongs to (for grouping/filter).
    namespace_by_uuid: dict[str, str] = {}
    for uuid_str in agent_names:
        namespace_by_uuid[uuid_str] = "Agent"
    for uuid_str in collection_names:
        namespace_by_uuid[uuid_str] = "SkillCollection"
    for uuid_str in mcp_names:
        namespace_by_uuid[uuid_str] = "MCPServer"
    for uuid_str in skill_names:
        namespace_by_uuid.setdefault(uuid_str, "Skill")

    workspace_member_ids = await _workspace_member_ids(user_context, db_session)

    items: list[RelationshipItem] = []
    for t in await _resource_tuples(
        graph_client,
        [
            object_id
            for object_id, object_namespace in namespace_by_uuid.items()
            if namespace is None or object_namespace == namespace
        ],
    ):
        if t.relation not in _GRANT_LABEL:
            continue
        object_id = str(t.object)
        object_namespace = namespace_by_uuid.get(object_id)
        if object_namespace is None:
            continue
        if namespace is not None and object_namespace != namespace:
            continue

        subject_repr = t.subject_id or ""
        subject_kind: Literal["agent", "user", "workspace"]
        subject_name: str
        if subject_repr.startswith("Agent:"):
            subject_kind = "agent"
            sid = subject_repr.split(":", 1)[1]
            subject_name = agent_names.get(sid, sid)
        elif subject_repr.startswith("User:"):
            subject_kind = "user"
            uid = subject_repr.split(":", 1)[1]
            if uid not in workspace_member_ids and uid not in agent_names:
                continue
            subject_name = uid
        else:
            continue

        object_name = (
            agent_names.get(object_id)
            or collection_names.get(object_id)
            or mcp_names.get(object_id)
            or skill_names.get(object_id)
            or object_id
        )
        fanout = skill_counts.get(object_id) if object_namespace == "SkillCollection" else None
        items.append(
            RelationshipItem(
                namespace=object_namespace,
                object=object_id,
                object_name=object_name,
                relation=_GRANT_LABEL[t.relation],
                subject=subject_repr,
                subject_kind=subject_kind,
                subject_name=subject_name,
                fanout=fanout,
                direct=object_namespace == "Skill",
            )
        )

    return RelationshipsResponse(relationships=items, count=len(items))


@router.post(
    "/relationships",
    status_code=201,
    dependencies=[
        enforced_in_handler("workspace admin, asserted before any graph or database read")
    ],
)
async def create_relationship(
    payload: RelationshipWriteRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> dict:
    """Grant a resource-ownership relation via the configured graph backend."""
    graph_client = get_graph_client()
    await _assert_workspace_admin(user_context)
    await _assert_object_in_workspace(payload.namespace, payload.object, user_context, db_session)
    await _assert_subject_in_workspace(payload.subject_id or "", user_context, db_session)
    relationship = _to_resource_grant(payload)
    try:
        await graph_client.write_tuple(relationship)
    except OpenFGAError as exc:
        logger.exception("Failed to write graph relationship %s", relationship)
        raise HTTPException(status_code=503, detail="Graph authorization write failed") from exc
    await _audit_grant("access.grant", payload, user_context, db_session)
    return {"ok": True}


@router.delete(
    "/relationships",
    status_code=204,
    dependencies=[
        enforced_in_handler("workspace admin, asserted before any graph or database read")
    ],
)
async def delete_relationship(
    payload: RelationshipWriteRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> None:
    """Revoke a resource-ownership relation from the configured graph backend."""
    graph_client = get_graph_client()
    await _assert_workspace_admin(user_context)
    await _assert_object_in_workspace(payload.namespace, payload.object, user_context, db_session)
    relationship = _to_resource_grant(payload)
    try:
        await graph_client.delete_tuple(relationship)
    except OpenFGAError as exc:
        logger.exception("Failed to delete graph relationship %s", relationship)
        raise HTTPException(status_code=503, detail="Graph authorization delete failed") from exc
    await _audit_grant("access.revoke", payload, user_context, db_session)


async def _audit_grant(
    action: str,
    payload: RelationshipWriteRequest,
    user_context: UserContext,
    db_session: AsyncSession,
) -> None:
    """Record who gave or took a role on which resource, and from whom."""
    await AuditService(db_session, user_context).record(
        action,
        "access_grant",
        payload.object,
        event_metadata={
            "namespace": payload.namespace,
            "relation": payload.relation,
            "subject_id": payload.subject_id,
        },
    )


@router.post(
    "/check",
    response_model=CheckResponse,
    dependencies=[
        enforced_in_handler("workspace admin, asserted before any graph or database read")
    ],
)
async def check_permission(
    payload: CheckRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> CheckResponse:
    """Check whether a subject has a permission on a resource."""
    await _assert_workspace_admin(user_context)
    graph_client = get_graph_client()
    await _assert_object_in_workspace(payload.namespace, payload.object, user_context, db_session)
    await _assert_subject_in_workspace(payload.subject_id, user_context, db_session)
    bit = _VERB_TO_BIT.get(payload.relation, payload.relation)
    if bit not in {"can_read", "can_write", "can_manage"}:
        return CheckResponse(allowed=False)
    try:
        result = await graph_client.check(
            namespace="resource",
            object=payload.object,
            relation=bit,
            subject_id=payload.subject_id,
        )
    except OpenFGAError as exc:
        logger.exception(
            "Graph authorization check failed (subject=%s resource:%s#%s)",
            payload.subject_id,
            payload.object,
            bit,
        )
        raise HTTPException(status_code=503, detail="Graph authorization check failed") from exc
    return CheckResponse(allowed=result.allowed)


@router.post(
    "/resolve",
    response_model=ResolveResponse,
    dependencies=[
        enforced_in_handler("workspace admin, asserted before any graph or database read")
    ],
)
async def resolve_access(
    payload: ResolveRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> ResolveResponse:
    """Resolve why (and how) a subject can access a resource.

    ``allowed`` is computed via the graph backend; ``paths`` are derived from the
    direct ``resource`` grants matching the subject so the UI can render the
    derivation. Grants inherited through ``project``/``role`` still affect
    ``allowed`` but are not expanded into hops here.
    """
    await _assert_workspace_admin(user_context)
    verb = _VERB_BY_KIND[payload.resource_kind]
    namespace = {
        "skill": "Skill",
        "collection": "SkillCollection",
        "mcp": "MCPServer",
        "agent": "Agent",
    }[payload.resource_kind]
    await _assert_object_in_workspace(namespace, payload.resource_id, user_context, db_session)
    await _assert_subject_in_workspace(payload.subject_id, user_context, db_session)

    bit = _VERB_TO_BIT[verb]
    graph_client = get_graph_client()
    allowed = False
    try:
        result = await graph_client.check(
            namespace="resource",
            object=payload.resource_id,
            relation=bit,
            subject_id=payload.subject_id,
        )
        allowed = result.allowed
    except OpenFGAError:
        logger.exception(
            "Graph authorization check failed during resolve (subject=%s resource:%s#%s)",
            payload.subject_id,
            payload.resource_id,
            bit,
        )

    factory = RepositoryFactory(db_session, user_context)
    agent_repo = factory.create_repository(AgentRepository)
    agent_names = {str(a.id): a.name for a in await agent_repo.list_all()}

    agent_uuid = (
        payload.subject_id.split(":", 1)[1]
        if payload.subject_id.startswith("Agent:")
        else payload.subject_id
    )
    subject_name = agent_names.get(agent_uuid, agent_uuid)
    subject_kind = "agent" if payload.subject_id.startswith("Agent:") else "user"
    subject_hop = ResolveHop(
        id=payload.subject_id,
        name=subject_name,
        kind=subject_kind,
        color=_color("agent", 0),
    )

    paths: list[ResolvePath] = []
    best_rank = 0
    effective_relation: str | None = None

    for t in await _resource_tuples(graph_client, [payload.resource_id]):
        if str(t.object) != payload.resource_id:
            continue
        if t.relation not in _GRANT_LABEL:
            continue
        if not (t.subject_id and t.subject_id == payload.subject_id):
            continue
        label = _GRANT_LABEL[t.relation]
        paths.append(
            ResolvePath(
                relation=label,
                hops=[
                    subject_hop,
                    ResolveHop(
                        id=f"resource:{payload.resource_id}",
                        name=payload.resource_kind,
                        kind=payload.resource_kind,
                        color=_color("collection", 0),
                    ),
                ],
                rels=[label],
            )
        )
        rank = _GRANT_RANK[t.relation]
        if rank > best_rank:
            best_rank = rank
            effective_relation = label

    return ResolveResponse(
        allowed=allowed,
        effective_relation=effective_relation,
        verb=verb,
        paths=paths,
    )


@router.post(
    "/sync",
    response_model=SyncResponse,
    dependencies=[
        enforced_in_handler("workspace admin, asserted before any graph or database read")
    ],
)
async def sync_grants(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> SyncResponse:
    """Mirror workspace membership into the graph backend (idempotent).

    Resource ownership is granted at create time by ``grant_resource_owner`` and
    was backfilled onto the ``resource`` model, so this endpoint only ensures the
    workspace-member tuples that gate group defaults are present.
    """
    graph_client = get_graph_client()
    await _assert_workspace_admin(user_context)

    written = 0

    owner_query = select(Workspace.owner_user_id).where(Workspace.id == user_context.workspace_id)
    owner_user_id = (await db_session.execute(owner_query)).scalar_one_or_none()
    member_query = select(WorkspaceMembership.user_id).where(
        WorkspaceMembership.workspace_id == user_context.workspace_id
    )
    member_ids = {str(row.user_id) for row in (await db_session.execute(member_query)).all()}
    if owner_user_id:
        member_ids.add(str(owner_user_id))
    for member_id in sorted(member_ids):
        await write_tuple_idempotent(
            graph_client,
            RelationTuple(
                namespace="Workspace",
                object=user_context.workspace_id,
                relation="members",
                subject_id=f"User:{member_id}",
            ),
        )
        written += 1

    return SyncResponse(written=written, collections=0)
