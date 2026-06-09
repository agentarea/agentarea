"""Tests for skill collection repository, service, and API endpoints."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents.application.collection_service import SkillCollectionService
from agentarea_agents.domain.collection_models import (
    SkillCollection,
    collection_skills_table,
)
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.infrastructure.collection_repository import (
    SkillCollectionRepository,
)
from agentarea_api.api.v1 import rebac, skill_collections
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_mcp.domain.models import MCPServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Tables needed across the collection + skill graph (SQLite in-memory).
_TABLES = [
    Agent.__table__,
    Skill.__table__,
    SkillCollection.__table__,
    MCPServer.__table__,
    collection_skills_table,
    agent_skills_table,
]


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(sync_conn, tables=_TABLES)
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _context(workspace_id: str = "workspace-a") -> UserContext:
    return UserContext(user_id=f"user-{workspace_id}", workspace_id=workspace_id)


async def _make_skill(session: AsyncSession, context: UserContext, name: str) -> Skill:
    skill = Skill(
        name=name,
        slug=name.lower().replace(" ", "-"),
        workspace_id=context.workspace_id,
        created_by=context.user_id,
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


# ---------------------------------------------------------------------------
# Repository + service
# ---------------------------------------------------------------------------


async def test_create_and_list_collection_with_skill_count(session_factory):
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))

        collection = await service.create(name="My Pack", description="desc")
        assert collection.slug == "my-pack"
        assert collection.workspace_id == context.workspace_id

        skill = await _make_skill(session, context, "Skill One")
        await service.add_skill(collection.id, skill.id)

        summaries = await service.list_collections()
        assert len(summaries) == 1
        assert summaries[0].collection.id == collection.id
        assert summaries[0].skill_count == 1


async def test_add_and_remove_skill(session_factory):
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")
        skill = await _make_skill(session, context, "S")

        await service.add_skill(collection.id, skill.id)
        repo = SkillCollectionRepository(session, context)
        assert await repo.skill_count(collection.id) == 1

        # Idempotent add.
        await service.add_skill(collection.id, skill.id)
        assert await repo.skill_count(collection.id) == 1

        await service.remove_skill(collection.id, skill.id)
        assert await repo.skill_count(collection.id) == 0


async def test_collections_are_workspace_scoped(session_factory):
    async with session_factory() as session:
        context_a = _context("workspace-a")
        context_b = _context("workspace-b")

        await SkillCollectionService(RepositoryFactory(session, context_a)).create(name="A pack")

        listed_b = await SkillCollectionService(
            RepositoryFactory(session, context_b)
        ).list_collections()
        assert listed_b == []


async def test_get_collection_with_skills(session_factory):
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")
        skill = await _make_skill(session, context, "Skill X")
        await service.add_skill(collection.id, skill.id)

        loaded = await service.get(collection.id)
        assert loaded is not None
        assert [s.id for s in loaded.skills] == [skill.id]


async def test_update_collection_name_keeps_slug(session_factory):
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Original")
        original_slug = collection.slug

        updated = await service.update(collection.id, name="Renamed")
        assert updated is not None
        assert updated.name == "Renamed"
        assert updated.slug == original_slug


async def test_delete_collection(session_factory):
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")

        assert await service.delete(collection.id) is True
        assert await service.get(collection.id) is None


# ---------------------------------------------------------------------------
# Collection CRUD API (Keto disabled — DB still works, no tuple writes)
# ---------------------------------------------------------------------------


async def test_api_add_skill_without_keto(session_factory, monkeypatch):
    monkeypatch.setattr(skill_collections, "get_keto", lambda: None)
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")
        skill = await _make_skill(session, context, "S")

        await skill_collections.add_skill_to_collection(
            collection.id,
            skill_collections.AddSkillRequest(skill_id=skill.id),
            context,
            session,
        )

        repo = SkillCollectionRepository(session, context)
        assert await repo.skill_count(collection.id) == 1


async def test_api_add_skill_writes_keto_tuple(session_factory, monkeypatch):
    keto = AsyncMock()
    monkeypatch.setattr(skill_collections, "get_keto", lambda: keto)
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")
        skill = await _make_skill(session, context, "S")

        await skill_collections.add_skill_to_collection(
            collection.id,
            skill_collections.AddSkillRequest(skill_id=skill.id),
            context,
            session,
        )

        keto.write_tuple.assert_awaited_once()
        written = keto.write_tuple.call_args.args[0]
        assert written.namespace == "Skill"
        assert written.object == str(skill.id)
        assert written.relation == "collections"
        assert written.subject_id == f"SkillCollection:{collection.id}"


# ---------------------------------------------------------------------------
# ReBAC graph / tuples / resolve API
# ---------------------------------------------------------------------------


async def test_graph_disabled_still_lists_nodes(session_factory, monkeypatch):
    monkeypatch.setattr(rebac, "get_keto", lambda: None)
    async with session_factory() as session:
        context = _context()
        service = SkillCollectionService(RepositoryFactory(session, context))
        await service.create(name="Pack")
        await _make_skill(session, context, "Skill A")
        await _make_skill(session, context, "Skill B")

        result = await rebac.get_graph(context, session)

        assert result.enabled is False
        kinds = {n.kind for n in result.nodes}
        assert "collection" in kinds
        assert result.edges == []
        assert result.stats.governed_skill_count == 2
        assert result.stats.rule_count == 0


async def test_graph_builds_edges_from_keto_tuples(session_factory, monkeypatch):
    async with session_factory() as session:
        context = _context()
        agent = Agent(
            name="Writer",
            slug="writer",
            workspace_id=context.workspace_id,
            created_by=context.user_id,
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")

        from agentarea_common.rebac import RelationTuple

        keto = AsyncMock()

        async def fake_query_all(query):
            if query.namespace == "SkillCollection":
                return [
                    RelationTuple(
                        namespace="SkillCollection",
                        object=str(collection.id),
                        relation="editors",
                        subject_id=f"Agent:{agent.id}",
                    )
                ]
            return []

        keto.query_all_tuples.side_effect = fake_query_all
        monkeypatch.setattr(rebac, "get_keto", lambda: keto)

        result = await rebac.get_graph(context, session)

        assert result.enabled is True
        assert len(result.edges) == 1
        edge = result.edges[0]
        assert edge["from"] == f"Agent:{agent.id}"
        assert edge["to"] == f"SkillCollection:{collection.id}"
        assert edge["relation"] == "editor"
        assert result.stats.rule_count == 1


async def test_tuples_disabled_returns_empty(session_factory, monkeypatch):
    monkeypatch.setattr(rebac, "get_keto", lambda: None)
    async with session_factory() as session:
        context = _context()
        result = await rebac.list_tuples(context, session)
        assert result.count == 0
        assert result.tuples == []


async def test_tuples_maps_collection_grant(session_factory, monkeypatch):
    async with session_factory() as session:
        context = _context()
        agent = Agent(
            name="Writer",
            slug="writer",
            workspace_id=context.workspace_id,
            created_by=context.user_id,
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")
        skill = await _make_skill(session, context, "S")
        await service.add_skill(collection.id, skill.id)

        from agentarea_common.rebac import RelationTuple

        keto = AsyncMock()

        async def fake_query_all(query):
            if query.namespace == "SkillCollection":
                return [
                    RelationTuple(
                        namespace="SkillCollection",
                        object=str(collection.id),
                        relation="editors",
                        subject_id=f"Agent:{agent.id}",
                    )
                ]
            return []

        keto.query_all_tuples.side_effect = fake_query_all
        monkeypatch.setattr(rebac, "get_keto", lambda: keto)

        result = await rebac.list_tuples(context, session, namespace="SkillCollection")

        assert result.count == 1
        item = result.tuples[0]
        assert item.object_name == "Pack"
        assert item.subject_kind == "agent"
        assert item.subject_name == "Writer"
        assert item.fanout == 1


async def test_resolve_computes_collection_path(session_factory, monkeypatch):
    async with session_factory() as session:
        context = _context()
        agent = Agent(
            name="Writer",
            slug="writer",
            workspace_id=context.workspace_id,
            created_by=context.user_id,
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        service = SkillCollectionService(RepositoryFactory(session, context))
        collection = await service.create(name="Pack")
        skill = await _make_skill(session, context, "S")
        await service.add_skill(collection.id, skill.id)

        from agentarea_common.rebac import CheckResult, RelationTuple

        keto = AsyncMock()
        keto.check.return_value = CheckResult(allowed=True)

        async def fake_query_all(query):
            if query.namespace == "SkillCollection":
                return [
                    RelationTuple(
                        namespace="SkillCollection",
                        object=str(collection.id),
                        relation="editors",
                        subject_id=f"Agent:{agent.id}",
                    )
                ]
            return []

        keto.query_all_tuples.side_effect = fake_query_all
        monkeypatch.setattr(rebac, "get_keto", lambda: keto)

        req = rebac.ResolveRequest(
            subject_id=f"Agent:{agent.id}",
            resource_kind="skill",
            resource_id=str(skill.id),
        )
        result = await rebac.resolve_access(req, context, session)

        assert result.allowed is True
        assert result.verb == "use"
        assert result.effective_relation == "editor"
        assert len(result.paths) == 1
        path = result.paths[0]
        assert path.relation == "editor"
        assert [h.kind for h in path.hops] == ["agent", "collection"]
        assert path.rels == ["editor", "contains"]


async def test_check_disabled_returns_false(session_factory, monkeypatch):
    monkeypatch.setattr(rebac, "get_keto", lambda: None)
    context = _context()
    req = rebac.CheckRequest(
        namespace="Skill", object=str(uuid4()), relation="use", subject_id="Agent:x"
    )
    result = await rebac.check_permission(req, context)
    assert result.allowed is False


async def test_create_tuple_disabled_raises_503(monkeypatch):
    monkeypatch.setattr(rebac, "get_keto", lambda: None)
    context = _context()
    req = rebac.TupleWriteRequest(
        namespace="Skill", object=str(uuid4()), relation="viewers", subject_id="Agent:x"
    )
    with pytest.raises(rebac.HTTPException) as exc_info:
        await rebac.create_tuple(req, context, None)  # db_session unused: 503 precedes the guard
    assert exc_info.value.status_code == 503
