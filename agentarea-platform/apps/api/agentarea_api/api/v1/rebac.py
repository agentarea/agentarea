"""ReBAC (Ory Keto) access explorer API.

Surfaces the authorization relationship graph that the frontend access explorer
renders: nodes (agents, skill collections, MCP servers), edges (grant tuples),
permission checks, path resolution, and a one-shot sync that mirrors existing
grants into Keto and seeds a starter "All skills" collection.

When ``KETO_ENABLED`` is false, read endpoints respond with ``enabled: false``
and still list the DB-backed nodes; write endpoints return HTTP 503.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID

from agentarea_agents.domain.collection_models import collection_skills_table
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.infrastructure.collection_repository import (
    SkillCollectionRepository,
)
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.auth import UserContextDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.infrastructure.database import get_db_session
from agentarea_common.rebac import (
    KetoClient,
    KetoError,
    KetoUnavailableError,
    RelationQuery,
    RelationTuple,
    SubjectSet,
)
from agentarea_common.utils.slug import generate_slug
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rebac", tags=["rebac"])

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
_VERB_BY_KIND = {"skill": "use", "mcp": "connect", "agent": "operate"}
_NAMESPACE_BY_KIND = {"skill": "Skill", "mcp": "MCPServer", "agent": "Agent"}


def get_keto() -> KetoClient | None:
    """Resolve the shared KetoClient, or None when Keto is disabled.

    Prefers the singleton registered in the DI container at startup; falls back
    to building one ad-hoc from settings if enabled but not yet registered.
    """
    settings = get_settings()
    if not settings.keto.KETO_ENABLED:
        return None
    try:
        return get_container().get(KetoClient)
    except ValueError:
        return KetoClient(
            read_url=settings.keto.KETO_READ_URL,
            write_url=settings.keto.KETO_WRITE_URL,
            timeout_seconds=settings.keto.KETO_TIMEOUT_SECONDS,
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


class TupleItem(BaseModel):
    namespace: str
    object: str
    object_name: str
    relation: str
    subject: str
    subject_kind: Literal["agent", "user", "workspace"]
    subject_name: str
    fanout: int | None = None
    direct: bool


class TuplesResponse(BaseModel):
    tuples: list[TupleItem]
    count: int


class SubjectSetBody(BaseModel):
    namespace: str
    object: str
    relation: str


class TupleWriteRequest(BaseModel):
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
    resource_kind: Literal["skill", "mcp", "agent"]
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


def _to_relation_tuple(payload: TupleWriteRequest) -> RelationTuple:
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


async def _workspace_tuples(keto: KetoClient, namespace: str) -> list[RelationTuple]:
    """Query all tuples for a namespace, tolerating Keto outages with a warning."""
    try:
        return await keto.query_all_tuples(RelationQuery(namespace=namespace))
    except (KetoError, KetoUnavailableError):
        logger.exception("Failed to query Keto tuples for namespace=%s", namespace)
        return []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> GraphResponse:
    """Return the full authorization graph for the current workspace."""
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
    governed_skill_count = len((await db_session.execute(skill_count_query)).all())

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

    keto = get_keto()
    edges: list[dict] = []
    rule_count = 0
    direct_exception_count = 0

    if keto is not None:
        collection_tuples = await _workspace_tuples(keto, "SkillCollection")
        for t in collection_tuples:
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

        mcp_tuples = await _workspace_tuples(keto, "MCPServer")
        for t in mcp_tuples:
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

        skill_tuples = await _workspace_tuples(keto, "Skill")
        for t in skill_tuples:
            if t.relation in _RELATION_LABEL and t.subject_id and t.subject_id.startswith("Agent:"):
                direct_exception_count += 1

    stats = GraphStats(
        governed_skill_count=governed_skill_count,
        rule_count=rule_count,
        direct_exception_count=direct_exception_count,
    )
    return GraphResponse(
        enabled=keto is not None,
        nodes=nodes,
        edges=edges,
        stats=stats,
    )


@router.get("/tuples", response_model=TuplesResponse)
async def list_tuples(
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    namespace: str | None = None,
) -> TuplesResponse:
    """List relation tuples, enriched with object/subject display names."""
    keto = get_keto()
    if keto is None:
        return TuplesResponse(tuples=[], count=0)

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

    namespaces = [namespace] if namespace else ["SkillCollection", "Skill", "MCPServer", "Agent"]
    items: list[TupleItem] = []
    for ns in namespaces:
        for t in await _workspace_tuples(keto, ns):
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
                TupleItem(
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

    return TuplesResponse(tuples=items, count=len(items))


@router.post("/tuples", status_code=201)
async def create_tuple(
    payload: TupleWriteRequest,
    user_context: UserContextDep,
) -> dict:
    """Write a relation tuple to Keto."""
    keto = get_keto()
    if keto is None:
        raise HTTPException(status_code=503, detail="Keto is disabled")
    tuple_ = _to_relation_tuple(payload)
    try:
        await keto.write_tuple(tuple_)
    except (KetoError, KetoUnavailableError) as exc:
        logger.exception("Failed to write Keto tuple %s", tuple_)
        raise HTTPException(status_code=503, detail="Keto write failed") from exc
    return {"ok": True}


@router.delete("/tuples", status_code=204)
async def delete_tuple(
    payload: TupleWriteRequest,
    user_context: UserContextDep,
) -> None:
    """Delete a relation tuple from Keto."""
    keto = get_keto()
    if keto is None:
        raise HTTPException(status_code=503, detail="Keto is disabled")
    tuple_ = _to_relation_tuple(payload)
    try:
        await keto.delete_tuple(tuple_)
    except (KetoError, KetoUnavailableError) as exc:
        logger.exception("Failed to delete Keto tuple %s", tuple_)
        raise HTTPException(status_code=503, detail="Keto delete failed") from exc


@router.post("/check", response_model=CheckResponse)
async def check_permission(
    payload: CheckRequest,
    user_context: UserContextDep,
) -> CheckResponse:
    """Check whether a subject has a relation on an object."""
    keto = get_keto()
    if keto is None:
        return CheckResponse(allowed=False)
    try:
        result = await keto.check(
            namespace=payload.namespace,
            object=payload.object,
            relation=payload.relation,
            subject_id=payload.subject_id,
        )
    except (KetoError, KetoUnavailableError) as exc:
        logger.exception(
            "Keto check failed (subject=%s %s:%s#%s)",
            payload.subject_id,
            payload.namespace,
            payload.object,
            payload.relation,
        )
        raise HTTPException(status_code=503, detail="Keto check failed") from exc
    return CheckResponse(allowed=result.allowed)


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_access(
    payload: ResolveRequest,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
) -> ResolveResponse:
    """Resolve why (and how) a subject can access a resource.

    ``allowed`` is computed via a Keto check; ``paths`` are derived by traversing
    the workspace tuples directly so the UI can render the derivation.
    """
    verb = _VERB_BY_KIND[payload.resource_kind]
    namespace = _NAMESPACE_BY_KIND[payload.resource_kind]

    keto = get_keto()
    allowed = False
    if keto is not None:
        try:
            result = await keto.check(
                namespace=namespace,
                object=payload.resource_id,
                relation=verb,
                subject_id=payload.subject_id,
            )
            allowed = result.allowed
        except (KetoError, KetoUnavailableError):
            logger.exception(
                "Keto check failed during resolve (subject=%s %s:%s#%s)",
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

    if payload.resource_kind == "skill" and keto is not None:
        # Collections that contain this skill.
        skill_uuid = UUID(payload.resource_id)
        membership_query = select(collection_skills_table.c.collection_id).where(
            collection_skills_table.c.skill_id == skill_uuid
        )
        member_collections = {
            str(row.collection_id) for row in (await db_session.execute(membership_query)).all()
        }
        member_collections &= collection_ids

        collection_tuples = await _workspace_tuples(keto, "SkillCollection")
        for t in collection_tuples:
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

        # Direct skill grants (exceptions).
        skill_tuples = await _workspace_tuples(keto, "Skill")
        for t in skill_tuples:
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
    """Mirror existing grants into Keto and seed a starter collection.

    Idempotent: safe to call repeatedly. Steps:
      1. If no collections exist, create "All skills" containing every workspace
         skill and grant ``SkillCollection:<id>#viewers@Workspace:<wid>#members``.
      2. For each collection_skills row, write
         ``Skill:<sid>#collections@SkillCollection:<cid>``.
      3. For each agent_skills row, write ``Skill:<sid>#viewers@Agent:<aid>``.
    """
    keto = get_keto()
    if keto is None:
        raise HTTPException(status_code=503, detail="Keto is disabled")

    factory = RepositoryFactory(db_session, user_context)
    collection_repo = factory.create_repository(SkillCollectionRepository)

    written = 0
    collections_created = 0

    existing_collections = await collection_repo.list_all()

    # Workspace skill ids.
    skill_ids_query = select(Skill.id).where(Skill.workspace_id == user_context.workspace_id)
    skill_ids = [str(row.id) for row in (await db_session.execute(skill_ids_query)).all()]

    # Step 1: seed "All skills" if no collections exist.
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
            await keto.write_tuple(
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
        except (KetoError, KetoUnavailableError) as exc:
            logger.exception("Failed to seed Keto default-viewer tuple")
            raise HTTPException(status_code=503, detail="Keto write failed") from exc

    # Step 2: mirror collection memberships (scoped to workspace collections).
    workspace_collection_ids = {str(c.id) for c in await collection_repo.list_all()}
    membership_query = select(
        collection_skills_table.c.collection_id,
        collection_skills_table.c.skill_id,
    )
    for row in (await db_session.execute(membership_query)).all():
        cid = str(row.collection_id)
        if cid not in workspace_collection_ids:
            continue
        try:
            await keto.write_tuple(
                RelationTuple(
                    namespace="Skill",
                    object=str(row.skill_id),
                    relation="collections",
                    subject_id=f"SkillCollection:{cid}",
                )
            )
            written += 1
        except (KetoError, KetoUnavailableError) as exc:
            logger.exception("Failed to mirror collection membership into Keto")
            raise HTTPException(status_code=503, detail="Keto write failed") from exc

    # Step 3: mirror direct agent_skills grants (scoped to workspace skills).
    workspace_skill_ids = set(skill_ids)
    agent_skill_query = select(
        agent_skills_table.c.agent_id,
        agent_skills_table.c.skill_id,
    )
    for row in (await db_session.execute(agent_skill_query)).all():
        if str(row.skill_id) not in workspace_skill_ids:
            continue
        try:
            await keto.write_tuple(
                RelationTuple(
                    namespace="Skill",
                    object=str(row.skill_id),
                    relation="viewers",
                    subject_id=f"Agent:{row.agent_id}",
                )
            )
            written += 1
        except (KetoError, KetoUnavailableError) as exc:
            logger.exception("Failed to mirror agent_skill grant into Keto")
            raise HTTPException(status_code=503, detail="Keto write failed") from exc

    return SyncResponse(written=written, collections=collections_created)
