"""Access-control relationship explorer API.

Surfaces the authorization relationship graph that the frontend access explorer
renders: nodes (agents, skill collections, MCP servers), access relationships,
permission checks, path resolution, and a one-shot sync that mirrors existing
grants into the configured graph backend and seeds a starter "All skills"
collection.

When no graph backend is enabled, read endpoints respond with ``enabled: false``
and still list the DB-backed nodes; write endpoints return HTTP 503. OpenFGA is
preferred when enabled; Keto remains supported as a migration fallback.
"""

import logging
from typing import Annotated, Literal
from urllib.parse import unquote
from uuid import UUID

from agentarea_agents.domain.collection_models import collection_skills_table
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.infrastructure.collection_repository import (
    SkillCollectionRepository,
)
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_common.auth import UserContext, UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.rebac import (
    KetoClient,
    KetoError,
    KetoUnavailableError,
    OpenFGAClient,
    OpenFGAError,
    OpenFGAUnavailableError,
    RelationQuery,
    RelationTuple,
    SubjectSet,
)
from agentarea_common.utils.slug import generate_slug
from agentarea_common.workspaces.models import Workspace, WorkspaceMembership
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["access-control"])

DatabaseSessionDep = Annotated[AsyncSession, Depends(get_db_session)]

# Stable colour palettes per node kind. Index into them by enumeration order so
# the same workspace always renders the same colours.
_COLORS: dict[str, list[str]] = {
    "agent": ["#6366f1", "#8b5cf6", "#a855f7", "#7c3aed", "#4f46e5"],
    "collection": ["#0ea5e9", "#06b6d4", "#0891b2", "#0284c7", "#22d3ee"],
    "mcp": ["#10b981", "#14b8a6", "#059669", "#16a34a", "#34d399"],
}

# Highest-wins ordering for collection grant relations.
_RELATION_RANK = {"viewers": 1, "editors": 2, "owners": 3}
_RELATION_LABEL = {"viewers": "user", "editors": "editor", "owners": "owner"}
_VERB_BY_KIND = {
    "skill": "use",
    "collection": "use",
    "mcp": "connect",
    "agent": "operate",
}
_NAMESPACE_BY_KIND = {
    "skill": "Skill",
    "collection": "SkillCollection",
    "mcp": "MCPServer",
    "agent": "Agent",
}


GraphClient = KetoClient | OpenFGAClient


def get_graph_client() -> GraphClient | None:
    """Resolve the shared graph client, or None when graph auth is disabled.

    OpenFGA is preferred over Keto during the migration.
    """
    settings = get_settings()
    if settings.access_control.ACCESS_CONTROL_BACKEND == "openfga":
        try:
            return get_container().get(OpenFGAClient)
        except ValueError:
            return OpenFGAClient(
                api_url=settings.openfga.ACCESS_CONTROL_OPENFGA_API_URL,
                store_id=settings.openfga.ACCESS_CONTROL_OPENFGA_STORE_ID,
                authorization_model_id=settings.openfga.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID,
                timeout_seconds=settings.openfga.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS,
            )
    if settings.access_control.ACCESS_CONTROL_BACKEND != "keto":
        return None
    try:
        return get_container().get(KetoClient)
    except ValueError:
        return KetoClient(
            read_url=settings.keto.ACCESS_CONTROL_KETO_READ_URL,
            write_url=settings.keto.ACCESS_CONTROL_KETO_WRITE_URL,
            timeout_seconds=settings.keto.ACCESS_CONTROL_KETO_TIMEOUT_SECONDS,
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

    def model_dump(self, **kwargs):  # type: ignore[override]
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


def _to_graph_relationship(payload: RelationshipWriteRequest) -> RelationTuple:
    if (payload.subject_id is None) == (payload.subject_set is None):
        raise HTTPException(
            status_code=422,
            detail="exactly one of subject_id or subject_set must be set",
        )
    subject_set = (
        SubjectSet(
            namespace=payload.subject_set.namespace,
            object=payload.subject_set.object,
            relation=payload.subject_set.relation,
        )
        if payload.subject_set is not None
        else None
    )
    return RelationTuple(
        namespace=payload.namespace,
        object=payload.object,
        relation=payload.relation,
        subject_id=payload.subject_id,
        subject_set=subject_set,
    )


async def _workspace_relationships(client: GraphClient, namespace: str) -> list[RelationTuple]:
    """Query relationships for a namespace, tolerating graph backend outages."""
    try:
        return await client.query_all_tuples(RelationQuery(namespace=namespace))
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError):
        logger.exception("Failed to query graph relationships for namespace=%s", namespace)
        return []


_NAMESPACE_REPOS: dict[str, type] = {
    "Agent": AgentRepository,
    "MCPServer": MCPServerRepository,
    "Skill": SkillRepository,
    "SkillCollection": SkillCollectionRepository,
}
_VIRTUAL_NAMESPACES = {"Tool", "ToolResource"}
_READABLE_NAMESPACES = set(_NAMESPACE_REPOS) | _VIRTUAL_NAMESPACES


def _virtual_object_workspace_id(namespace: str, object_id: str) -> str | None:
    if namespace == "ToolResource":
        object_id = object_id.split("~args~", 1)[0]
    if namespace not in _VIRTUAL_NAMESPACES:
        return None
    workspace_id, separator, _tool_name = object_id.partition("/")
    if not separator or not workspace_id:
        return None
    return unquote(workspace_id)


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


def _workspace_object_ids(
    agent_ids: set[str],
    collection_ids: set[str],
    skill_ids: set[str],
    mcp_ids: set[str],
) -> dict[str, set[str]]:
    return {
        "Agent": agent_ids,
        "SkillCollection": collection_ids,
        "Skill": skill_ids,
        "MCPServer": mcp_ids,
    }


async def _assert_object_in_workspace(
    namespace: str,
    object_id: str,
    user_context: UserContext,
    db_session: AsyncSession,
) -> None:
    """Raise 403/422 if namespace:object_id does not belong to the caller's workspace."""
    repo_cls = _NAMESPACE_REPOS.get(namespace)
    if repo_cls is None:
        if namespace in _VIRTUAL_NAMESPACES:
            if user_context is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{namespace} objects require a workspace-scoped id",
                )
            object_workspace_id = _virtual_object_workspace_id(namespace, object_id)
            if object_workspace_id != user_context.workspace_id:
                raise HTTPException(
                    status_code=403,
                    detail=f"{namespace}:{object_id} not found in your workspace",
                )
            return
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


def _relationship_is_in_workspace(
    relationship: RelationTuple,
    *,
    workspace_id: str,
    workspace_objects: dict[str, set[str]],
    workspace_member_ids: set[str],
) -> bool:
    if relationship.namespace in _VIRTUAL_NAMESPACES:
        if (
            _virtual_object_workspace_id(relationship.namespace, relationship.object)
            != workspace_id
        ):
            return False
    else:
        allowed_objects = workspace_objects.get(relationship.namespace)
        if allowed_objects is None or str(relationship.object) not in allowed_objects:
            return False

    if relationship.subject_set is not None:
        subject_set = relationship.subject_set
        if subject_set.namespace == "Workspace":
            return subject_set.object == workspace_id
        allowed_subjects = workspace_objects.get(subject_set.namespace)
        if allowed_subjects is None:
            return False
        return subject_set.object in allowed_subjects

    subject_id = relationship.subject_id or ""
    if subject_id.startswith("Agent:"):
        return subject_id.split(":", 1)[1] in workspace_objects["Agent"]
    if subject_id.startswith("User:"):
        return subject_id.split(":", 1)[1] in workspace_member_ids
    if subject_id.startswith("Workspace:"):
        return subject_id.split(":", 1)[1] == workspace_id
    return False


def _assert_relationship_mutable_namespace(namespace: str) -> None:
    if namespace in _VIRTUAL_NAMESPACES:
        raise HTTPException(
            status_code=422,
            detail=f"Use the tool-access API to mutate {namespace} grants",
        )


async def _assert_workspace_admin(user_context: UserContext) -> None:
    """Only a workspace owner/admin may mutate the authorization graph.

    Writing/deleting relationships grants or revokes access across the
    workspace, so it must not be available to every member.
    """
    from agentarea_common.auth.authorization import AuthorizationService
    from agentarea_common.di.container import resolve

    authz = resolve(AuthorizationService)
    if not await authz.can_write_workspace(user_context, user_context.workspace_id):
        raise HTTPException(
            status_code=403,
            detail="Only a workspace admin may modify the authorization graph",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/graph", response_model=GraphResponse)
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

    # All skills in the workspace (used for stats + node counts).
    skill_count_query = select(Skill.id).where(Skill.workspace_id == user_context.workspace_id)
    skill_ids = {str(row.id) for row in (await db_session.execute(skill_count_query)).all()}
    governed_skill_count = len(skill_ids)

    nodes: list[GraphNode] = []
    agent_ids: set[str] = set()
    collection_ids: set[str] = set()
    mcp_ids: set[str] = set()

    for index, agent in enumerate(agents):
        nodes.append(
            GraphNode(
                id=f"Agent:{agent.id}",
                kind="agent",
                name=agent.name,
                subtitle="agent",
                color=_color("agent", index),
            )
        )
        agent_ids.add(str(agent.id))

    for index, collection in enumerate(collections):
        skills_in = counts.get(str(collection.id), 0)
        nodes.append(
            GraphNode(
                id=f"SkillCollection:{collection.id}",
                kind="collection",
                name=collection.name,
                subtitle=f"{skills_in} skills",
                color=_color("collection", index),
                count=skills_in,
            )
        )
        collection_ids.add(str(collection.id))

    for index, server in enumerate(mcp_servers):
        nodes.append(
            GraphNode(
                id=f"MCPServer:{server.id}",
                kind="mcp",
                name=server.name,
                subtitle="MCP server",
                color=_color("mcp", index),
            )
        )
        mcp_ids.add(str(server.id))

    graph_client = get_graph_client()
    edges: list[dict] = []
    rule_count = 0
    direct_exception_count = 0

    if graph_client is not None:
        collection_relationships = await _workspace_relationships(graph_client, "SkillCollection")
        for t in collection_relationships:
            if str(t.object) not in collection_ids:
                continue
            if t.relation not in _RELATION_LABEL:
                continue
            rule_count += 1
            if t.subject_id and t.subject_id.startswith("Agent:"):
                agent_uuid = t.subject_id.split(":", 1)[1]
                if agent_uuid in agent_ids:
                    edges.append(
                        GraphEdge(
                            from_=f"Agent:{agent_uuid}",
                            to=f"SkillCollection:{t.object}",
                            relation=_RELATION_LABEL[t.relation],
                        ).model_dump()
                    )

        mcp_relationships = await _workspace_relationships(graph_client, "MCPServer")
        for t in mcp_relationships:
            if str(t.object) not in mcp_ids:
                continue
            if t.relation != "connectors":
                continue
            rule_count += 1
            if t.subject_id and t.subject_id.startswith("Agent:"):
                agent_uuid = t.subject_id.split(":", 1)[1]
                if agent_uuid in agent_ids:
                    edges.append(
                        GraphEdge(
                            from_=f"Agent:{agent_uuid}",
                            to=f"MCPServer:{t.object}",
                            relation="connect",
                        ).model_dump()
                    )

        skill_relationships = await _workspace_relationships(graph_client, "Skill")
        for t in skill_relationships:
            if str(t.object) not in skill_ids:
                continue
            if t.relation in _RELATION_LABEL and t.subject_id and t.subject_id.startswith("Agent:"):
                direct_exception_count += 1

    stats = GraphStats(
        governed_skill_count=governed_skill_count,
        rule_count=rule_count,
        direct_exception_count=direct_exception_count,
    )
    return GraphResponse(
        enabled=graph_client is not None,
        nodes=nodes,
        edges=edges,
        stats=stats,
    )


@router.get("/relationships", response_model=RelationshipsResponse)
async def list_relationships(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    namespace: str | None = None,
) -> RelationshipsResponse:
    """List authorization relationships enriched with display names."""
    await _assert_workspace_admin(user_context)
    graph_client = get_graph_client()
    if graph_client is None:
        return RelationshipsResponse(relationships=[], count=0)
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
    workspace_objects = _workspace_object_ids(
        set(agent_names),
        set(collection_names),
        set(skill_names),
        set(mcp_names),
    )
    workspace_member_ids = await _workspace_member_ids(user_context, db_session)

    namespaces = (
        [namespace]
        if namespace
        else ["SkillCollection", "Skill", "MCPServer", "Agent", "Tool", "ToolResource"]
    )
    items: list[RelationshipItem] = []
    for ns in namespaces:
        for t in await _workspace_relationships(graph_client, ns):
            if not _relationship_is_in_workspace(
                t,
                workspace_id=user_context.workspace_id,
                workspace_objects=workspace_objects,
                workspace_member_ids=workspace_member_ids,
            ):
                continue
            object_id = str(t.object)
            object_name = (
                collection_names.get(object_id)
                or skill_names.get(object_id)
                or mcp_names.get(object_id)
                or agent_names.get(object_id)
                or object_id
            )
            subject_kind: Literal["agent", "user", "workspace"]
            subject_name: str
            subject_repr: str
            if t.subject_set is not None:
                subject_kind = "workspace"
                subject_repr = str(t.subject_set)
                subject_name = "workspace members"
            else:
                subject_repr = t.subject_id or ""
                if subject_repr.startswith("Agent:"):
                    subject_kind = "agent"
                    sid = subject_repr.split(":", 1)[1]
                    subject_name = agent_names.get(sid, sid)
                elif subject_repr.startswith("User:"):
                    subject_kind = "user"
                    subject_name = subject_repr.split(":", 1)[1]
                else:
                    subject_kind = "user"
                    subject_name = subject_repr

            fanout = None
            if ns == "SkillCollection":
                fanout = skill_counts.get(object_id, 0)
            direct = ns == "Skill" and t.relation in _RELATION_LABEL

            items.append(
                RelationshipItem(
                    namespace=ns,
                    object=object_id,
                    object_name=object_name,
                    relation=t.relation,
                    subject=subject_repr,
                    subject_kind=subject_kind,
                    subject_name=subject_name,
                    fanout=fanout,
                    direct=direct,
                )
            )

    return RelationshipsResponse(relationships=items, count=len(items))


@router.post("/relationships", status_code=201)
async def create_relationship(
    payload: RelationshipWriteRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> dict:
    """Write an authorization relationship to the configured graph backend."""
    graph_client = get_graph_client()
    if graph_client is None:
        raise HTTPException(status_code=503, detail="Graph authorization is disabled")
    await _assert_workspace_admin(user_context)
    _assert_relationship_mutable_namespace(payload.namespace)
    await _assert_object_in_workspace(payload.namespace, payload.object, user_context, db_session)
    # Validate the subject too: a subject_set pointing at one of our entity
    # namespaces must also belong to the caller's workspace, so admins cannot
    # grant access to/from an object in another workspace.
    if payload.subject_set is not None and payload.subject_set.namespace in _NAMESPACE_REPOS:
        await _assert_object_in_workspace(
            payload.subject_set.namespace,
            payload.subject_set.object,
            user_context,
            db_session,
        )
    elif payload.subject_set is not None and payload.subject_set.namespace == "Workspace":
        if payload.subject_set.object != user_context.workspace_id:
            raise HTTPException(status_code=403, detail="Subject workspace is not your workspace")
    elif payload.subject_id is not None:
        await _assert_subject_in_workspace(payload.subject_id, user_context, db_session)
    relationship = _to_graph_relationship(payload)
    try:
        await graph_client.write_tuple(relationship)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception("Failed to write graph relationship %s", relationship)
        raise HTTPException(status_code=503, detail="Graph authorization write failed") from exc
    return {"ok": True}


@router.delete("/relationships", status_code=204)
async def delete_relationship(
    payload: RelationshipWriteRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> None:
    """Delete an authorization relationship from the configured graph backend."""
    graph_client = get_graph_client()
    if graph_client is None:
        raise HTTPException(status_code=503, detail="Graph authorization is disabled")
    await _assert_workspace_admin(user_context)
    _assert_relationship_mutable_namespace(payload.namespace)
    await _assert_object_in_workspace(payload.namespace, payload.object, user_context, db_session)
    relationship = _to_graph_relationship(payload)
    try:
        await graph_client.delete_tuple(relationship)
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception("Failed to delete graph relationship %s", relationship)
        raise HTTPException(status_code=503, detail="Graph authorization delete failed") from exc


@router.post("/check", response_model=CheckResponse)
async def check_permission(
    payload: CheckRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> CheckResponse:
    """Check whether a subject has a relation on an object."""
    await _assert_workspace_admin(user_context)
    graph_client = get_graph_client()
    if graph_client is None:
        return CheckResponse(allowed=False)
    await _assert_object_in_workspace(payload.namespace, payload.object, user_context, db_session)
    await _assert_subject_in_workspace(payload.subject_id, user_context, db_session)
    try:
        result = await graph_client.check(
            namespace=payload.namespace,
            object=payload.object,
            relation=payload.relation,
            subject_id=payload.subject_id,
        )
    except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
        logger.exception(
            "Graph authorization check failed (subject=%s %s:%s#%s)",
            payload.subject_id,
            payload.namespace,
            payload.object,
            payload.relation,
        )
        raise HTTPException(status_code=503, detail="Graph authorization check failed") from exc
    return CheckResponse(allowed=result.allowed)


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_access(
    payload: ResolveRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> ResolveResponse:
    """Resolve why (and how) a subject can access a resource.

    ``allowed`` is computed via the graph backend; ``paths`` are derived by
    traversing workspace relationships directly so the UI can render the derivation.
    """
    await _assert_workspace_admin(user_context)
    verb = _VERB_BY_KIND[payload.resource_kind]
    namespace = _NAMESPACE_BY_KIND[payload.resource_kind]
    await _assert_object_in_workspace(namespace, payload.resource_id, user_context, db_session)
    await _assert_subject_in_workspace(payload.subject_id, user_context, db_session)

    graph_client = get_graph_client()
    allowed = False
    if graph_client is not None:
        try:
            result = await graph_client.check(
                namespace=namespace,
                object=payload.resource_id,
                relation=verb,
                subject_id=payload.subject_id,
            )
            allowed = result.allowed
        except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError):
            logger.exception(
                "Graph authorization check failed during resolve (subject=%s %s:%s#%s)",
                payload.subject_id,
                namespace,
                payload.resource_id,
                verb,
            )

    factory = RepositoryFactory(db_session, user_context)
    agent_repo = factory.create_repository(AgentRepository)
    collection_repo = factory.create_repository(SkillCollectionRepository)

    agent_names = {str(a.id): a.name for a in await agent_repo.list_all()}
    collection_records = await collection_repo.list_all()
    collection_names = {str(c.id): c.name for c in collection_records}
    collection_ids = set(collection_names)

    agent_uuid = (
        payload.subject_id.split(":", 1)[1]
        if payload.subject_id.startswith("Agent:")
        else payload.subject_id
    )
    agent_name = agent_names.get(agent_uuid, agent_uuid)
    agent_hop = ResolveHop(
        id=f"Agent:{agent_uuid}", name=agent_name, kind="agent", color=_color("agent", 0)
    )

    paths: list[ResolvePath] = []
    best_rank = 0
    effective_relation: str | None = None

    if payload.resource_kind == "skill" and graph_client is not None:
        # Collections that contain this skill.
        try:
            skill_uuid = UUID(payload.resource_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="resource_id is not a valid UUID") from None
        membership_query = select(collection_skills_table.c.collection_id).where(
            collection_skills_table.c.skill_id == skill_uuid
        )
        member_collections = {
            str(row.collection_id) for row in (await db_session.execute(membership_query)).all()
        }
        member_collections &= collection_ids

        collection_relationships = await _workspace_relationships(graph_client, "SkillCollection")
        for t in collection_relationships:
            if str(t.object) not in member_collections:
                continue
            if t.relation not in _RELATION_LABEL:
                continue
            if not (t.subject_id and t.subject_id == payload.subject_id):
                continue
            label = _RELATION_LABEL[t.relation]
            cid = str(t.object)
            paths.append(
                ResolvePath(
                    relation=label,
                    hops=[
                        agent_hop,
                        ResolveHop(
                            id=f"SkillCollection:{cid}",
                            name=collection_names.get(cid, cid),
                            kind="collection",
                            color=_color("collection", 0),
                        ),
                    ],
                    rels=[label, "contains"],
                )
            )
            rank = _RELATION_RANK[t.relation]
            if rank > best_rank:
                best_rank = rank
                effective_relation = label

    if payload.resource_kind == "collection" and graph_client is not None:
        collection_relationships = await _workspace_relationships(graph_client, "SkillCollection")
        for t in collection_relationships:
            if str(t.object) != payload.resource_id:
                continue
            if t.relation not in _RELATION_LABEL:
                continue
            if not (t.subject_id and t.subject_id == payload.subject_id):
                continue
            label = _RELATION_LABEL[t.relation]
            paths.append(
                ResolvePath(
                    relation=label,
                    hops=[
                        agent_hop,
                        ResolveHop(
                            id=f"SkillCollection:{payload.resource_id}",
                            name=collection_names.get(payload.resource_id, payload.resource_id),
                            kind="collection",
                            color=_color("collection", 0),
                        ),
                    ],
                    rels=[label],
                )
            )
            rank = _RELATION_RANK[t.relation]
            if rank > best_rank:
                best_rank = rank
                effective_relation = label

        # Direct skill grants (exceptions).
        skill_relationships = await _workspace_relationships(graph_client, "Skill")
        for t in skill_relationships:
            if str(t.object) != payload.resource_id:
                continue
            if t.relation not in _RELATION_LABEL:
                continue
            if not (t.subject_id and t.subject_id == payload.subject_id):
                continue
            label = _RELATION_LABEL[t.relation]
            paths.append(
                ResolvePath(
                    relation=label,
                    hops=[
                        agent_hop,
                        ResolveHop(
                            id=f"Skill:{payload.resource_id}",
                            name="skill",
                            kind="skill",
                            color=_color("collection", 1),
                        ),
                    ],
                    rels=[label],
                )
            )
            rank = _RELATION_RANK[t.relation]
            if rank > best_rank:
                best_rank = rank
                effective_relation = label

    return ResolveResponse(
        allowed=allowed,
        effective_relation=effective_relation,
        verb=verb,
        paths=paths,
    )


@router.post("/sync", response_model=SyncResponse)
async def sync_grants(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> SyncResponse:
    """Mirror existing grants into the graph backend and seed a starter collection.

    Idempotent: safe to call repeatedly. Steps:
      1. Mirror workspace members into the graph.
      2. If no collections exist, create "All skills" containing every workspace
         skill and grant workspace-member access to the collection.
      3. Mirror each collection membership relationship.
      4. Mirror each direct agent-to-skill grant.
    """
    graph_client = get_graph_client()
    if graph_client is None:
        raise HTTPException(status_code=503, detail="Graph authorization is disabled")
    await _assert_workspace_admin(user_context)

    factory = RepositoryFactory(db_session, user_context)
    collection_repo = factory.create_repository(SkillCollectionRepository)

    written = 0
    collections_created = 0

    existing_collections = await collection_repo.list_all()

    # Workspace skill ids.
    skill_ids_query = select(Skill.id).where(Skill.workspace_id == user_context.workspace_id)
    skill_ids = [str(row.id) for row in (await db_session.execute(skill_ids_query)).all()]

    # Step 1: mirror workspace members. The OpenFGA model uses Workspace#members
    # as the graph-native boundary for tool grants and collection defaults.
    owner_query = select(Workspace.owner_user_id).where(Workspace.id == user_context.workspace_id)
    owner_user_id = (await db_session.execute(owner_query)).scalar_one_or_none()
    member_query = select(WorkspaceMembership.user_id).where(
        WorkspaceMembership.workspace_id == user_context.workspace_id
    )
    member_ids = {str(row.user_id) for row in (await db_session.execute(member_query)).all()}
    if owner_user_id:
        member_ids.add(str(owner_user_id))
    for member_id in sorted(member_ids):
        try:
            await graph_client.write_tuple(
                RelationTuple(
                    namespace="Workspace",
                    object=user_context.workspace_id,
                    relation="members",
                    subject_id=f"User:{member_id}",
                )
            )
            written += 1
        except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
            logger.exception("Failed to mirror workspace member into graph backend")
            raise HTTPException(status_code=503, detail="Graph authorization write failed") from exc

    # Step 2: seed "All skills" if no collections exist.
    if not existing_collections and skill_ids:
        all_skills = await collection_repo.create(
            name="All skills",
            slug=generate_slug("All skills"),
            description="Every skill in the workspace.",
        )
        collections_created += 1
        for sid in skill_ids:
            await collection_repo.add_skill(all_skills.id, UUID(sid))
        try:
            await graph_client.write_tuple(
                RelationTuple(
                    namespace="SkillCollection",
                    object=str(all_skills.id),
                    relation="viewers",
                    subject_set=SubjectSet(
                        namespace="Workspace",
                        object=user_context.workspace_id,
                        relation="members",
                    ),
                )
            )
            written += 1
        except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
            logger.exception("Failed to seed graph default-viewer relationship")
            raise HTTPException(status_code=503, detail="Graph authorization write failed") from exc

    # Step 3: mirror collection memberships (scoped to workspace collections).
    workspace_cid_uuids = [c.id for c in existing_collections]
    membership_query = select(
        collection_skills_table.c.collection_id,
        collection_skills_table.c.skill_id,
    ).where(collection_skills_table.c.collection_id.in_(workspace_cid_uuids))
    for row in (await db_session.execute(membership_query)).all():
        cid = str(row.collection_id)
        try:
            await graph_client.write_tuple(
                RelationTuple(
                    namespace="Skill",
                    object=str(row.skill_id),
                    relation="collections",
                    subject_id=f"SkillCollection:{cid}",
                )
            )
            written += 1
        except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
            logger.exception("Failed to mirror collection membership into graph backend")
            raise HTTPException(status_code=503, detail="Graph authorization write failed") from exc

    # Step 4: mirror direct agent_skills grants (scoped to workspace skills).
    workspace_skill_uuids = [UUID(s) for s in skill_ids]
    agent_skill_query = select(
        agent_skills_table.c.agent_id,
        agent_skills_table.c.skill_id,
    ).where(agent_skills_table.c.skill_id.in_(workspace_skill_uuids))
    for row in (await db_session.execute(agent_skill_query)).all():
        try:
            await graph_client.write_tuple(
                RelationTuple(
                    namespace="Skill",
                    object=str(row.skill_id),
                    relation="viewers",
                    subject_id=f"Agent:{row.agent_id}",
                )
            )
            written += 1
        except (KetoError, KetoUnavailableError, OpenFGAError, OpenFGAUnavailableError) as exc:
            logger.exception("Failed to mirror agent_skill grant into graph backend")
            raise HTTPException(status_code=503, detail="Graph authorization write failed") from exc

    return SyncResponse(written=written, collections=collections_created)
