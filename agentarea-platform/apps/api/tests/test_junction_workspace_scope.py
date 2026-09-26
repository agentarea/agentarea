"""A link row may only join two resources of the caller's workspace (#494).

Junction tables carry no ``workspace_id``: the only thing keeping a project,
client, agent or skill bundle from pointing at another tenant's resource is the
check on both ends before the link is written, and the parent scope when it is
read. These tests run the real services on SQLite, then go through the REST
handlers and platform toolsets that front them.
"""

import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table, skill_members_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import clients as clients_router
from agentarea_api.api.v1 import projects as projects_router
from agentarea_api.tools import clients_toolset, projects_toolset
from agentarea_api.tools.clients_toolset import ClientsToolset
from agentarea_api.tools.projects_toolset import ProjectsToolset
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.di.container import get_container
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_common.testing import allow_all_permissions, install_graph_ownership_stub
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_registry.domain.models import Registry, RegistryItem, RegistryItemInstall
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.domain.auth_models import MCPAuthConfig
from agentarea_mcp.domain.client_models import Client, client_mcp_instances, client_skills
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_projects.application.service import ProjectService
from agentarea_projects.domain.models import (
    Project,
    project_agents,
    project_mcp_instances,
    project_skills,
)
from agentarea_projects.infrastructure.repository import ProjectRepository
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

OURS = UserContext(user_id="user-a", workspace_id="ws-a")
THEIRS = UserContext(user_id="user-b", workspace_id="ws-b")

_TABLES = [
    Agent.__table__,
    Skill.__table__,
    MCPAuthConfig.__table__,
    MCPServerInstance.__table__,
    Project.__table__,
    Client.__table__,
    PolicyRuleORM.__table__,
    AuditEventORM.__table__,
    agent_skills_table,
    skill_members_table,
    project_skills,
    project_agents,
    project_mcp_instances,
    client_skills,
    client_mcp_instances,
    # A skill id that is not the workspace's is looked up in the catalog next.
    Registry.__table__,
    RegistryItem.__table__,
    RegistryItemInstall.__table__,
]


@pytest.fixture(autouse=True)
def _graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(
        engine.sync_engine,
        "connect",
        lambda dbapi_connection, _record: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(sync_conn, tables=_TABLES)
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


async def _add(session: AsyncSession, row):
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


def _owned(ctx: UserContext) -> dict:
    return {"workspace_id": ctx.workspace_id, "created_by": ctx.user_id}


async def _skill(session, ctx, name="research") -> Skill:
    return await _add(session, Skill(name=name, slug=f"{name}-{uuid4().hex[:6]}", **_owned(ctx)))


async def _agent(session, ctx, name="writer") -> Agent:
    return await _add(session, Agent(name=name, slug=f"{name}-{uuid4().hex[:6]}", **_owned(ctx)))


async def _instance(session, ctx, name="github") -> MCPServerInstance:
    return await _add(
        session,
        MCPServerInstance(
            name=name, server_spec_id="spec", workspace_id=ctx.workspace_id, created_by=ctx.user_id
        ),
    )


async def _project(session, ctx) -> Project:
    return await _add(session, Project(name="launch", **_owned(ctx)))


async def _client(session, ctx) -> Client:
    return await _add(session, Client(name="codex", kind="harness", **_owned(ctx)))


async def _links(session, table, column: str, parent_id) -> set[str]:
    rows = await session.execute(select(table).where(getattr(table.c, column) == parent_id))
    return {str(v) for row in rows.all() for v in row}


# --- projects -----------------------------------------------------------------


def _projects(session, ctx=OURS) -> ProjectService:
    return ProjectService(ProjectRepository(session, ctx))


@pytest.mark.parametrize(
    ("method", "make_child", "table"),
    [
        ("add_skill", _skill, project_skills),
        ("add_agent", _agent, project_agents),
        ("add_mcp_instance", _instance, project_mcp_instances),
    ],
)
async def test_project_refuses_a_foreign_child(session, method, make_child, table):
    project = await _project(session, OURS)
    foreign = await make_child(session, THEIRS)

    with pytest.raises(NotFoundError):
        await getattr(_projects(session), method)(project.id, foreign.id)

    assert await _links(session, table, "project_id", project.id) == set()


@pytest.mark.parametrize(
    ("method", "make_child", "attr"),
    [
        ("add_skill", _skill, "skills"),
        ("add_agent", _agent, "agents"),
        ("add_mcp_instance", _instance, "mcp_instances"),
    ],
)
async def test_project_links_a_child_of_its_own_workspace(session, method, make_child, attr):
    project = await _project(session, OURS)
    child = await make_child(session, OURS)

    await getattr(_projects(session), method)(project.id, child.id)

    loaded = await _projects(session).get(project.id)
    assert [c.id for c in getattr(loaded, attr)] == [child.id]


async def test_foreign_project_cannot_be_linked_or_unlinked(session):
    theirs = await _project(session, THEIRS)
    their_skill = await _skill(session, THEIRS)
    await _projects(session, THEIRS).add_skill(theirs.id, their_skill.id)
    our_skill = await _skill(session, OURS)

    with pytest.raises(NotFoundError):
        await _projects(session).add_skill(theirs.id, our_skill.id)
    with pytest.raises(NotFoundError):
        await _projects(session).remove_skill(theirs.id, their_skill.id)

    assert await _links(session, project_skills, "project_id", theirs.id) == {
        str(theirs.id),
        str(their_skill.id),
    }


async def test_project_read_hides_a_foreign_child_already_linked(session):
    project = await _project(session, OURS)
    ours, foreign = await _skill(session, OURS, "ours"), await _skill(session, THEIRS, "theirs")
    await session.execute(
        project_skills.insert(),
        [
            {"project_id": project.id, "skill_id": ours.id},
            {"project_id": project.id, "skill_id": foreign.id},
        ],
    )
    await session.commit()
    session.expunge_all()

    by_id = await _projects(session).get(project.id)
    listed = await _projects(session).list()

    assert [s.id for s in by_id.skills] == [ours.id]
    assert [s.id for s in listed[0].skills] == [ours.id]


async def test_projects_rest_handler_refuses_a_foreign_skill(session):
    project = await _project(session, OURS)
    foreign = await _skill(session, THEIRS)

    with pytest.raises(NotFoundError):
        await projects_router.add_skill_to_project(
            project.id,
            projects_router.AssociationBody(id=str(foreign.id)),
            OURS,
            _projects(session),
        )


@pytest.fixture
def toolset_session(monkeypatch, session):
    @asynccontextmanager
    async def context():
        yield session, OURS, RepositoryFactory(session, OURS), None, None

    for module in (projects_toolset, clients_toolset):
        monkeypatch.setattr(module, "platform_context", context)
        monkeypatch.setattr(module, "platform_read_context", context)
    container = get_container()
    saved = dict(container._singletons)
    allow_all_permissions()
    with use_mcp_user_context(OURS):
        yield session
    container._singletons.clear()
    container._singletons.update(saved)


async def test_projects_toolset_refuses_a_foreign_agent(toolset_session):
    project = await _project(toolset_session, OURS)
    foreign = await _agent(toolset_session, THEIRS)

    with pytest.raises(NotFoundError):
        await ProjectsToolset().add_agent(project_id=str(project.id), agent_id=str(foreign.id))

    ours = await _agent(toolset_session, OURS)
    added = await ProjectsToolset().add_agent(project_id=str(project.id), agent_id=str(ours.id))
    assert json.loads(added) == {"added": True}


# --- clients ------------------------------------------------------------------


def _clients(session, ctx=OURS) -> ClientService:
    return ClientService(ClientRepository(session, ctx))


@pytest.mark.parametrize(
    ("method", "make_child", "table"),
    [
        ("add_skill", _skill, client_skills),
        ("add_mcp_instance", _instance, client_mcp_instances),
    ],
)
async def test_client_refuses_a_foreign_child(session, method, make_child, table):
    client = await _client(session, OURS)
    foreign = await make_child(session, THEIRS)

    with pytest.raises(NotFoundError):
        await getattr(_clients(session), method)(client.id, foreign.id)

    assert await _links(session, table, "client_id", client.id) == set()


async def test_client_links_children_of_its_own_workspace(session):
    client = await _client(session, OURS)
    skill, instance = await _skill(session, OURS), await _instance(session, OURS)

    await _clients(session).add_skill(client.id, skill.id)
    await _clients(session).add_mcp_instance(client.id, instance.id, "gh")

    loaded = await _clients(session).get(client.id)
    assert [s.id for s in loaded.skills] == [skill.id]
    assert [i.id for i in loaded.mcp_instances] == [instance.id]


async def test_foreign_client_cannot_be_unlinked(session):
    theirs = await _client(session, THEIRS)
    their_skill = await _skill(session, THEIRS)
    await _clients(session, THEIRS).add_skill(theirs.id, their_skill.id)

    with pytest.raises(NotFoundError):
        await _clients(session).remove_skill(theirs.id, their_skill.id)

    assert str(their_skill.id) in await _links(session, client_skills, "client_id", theirs.id)


async def test_client_endpoint_lookup_hides_a_foreign_skill_already_linked(session):
    client = await _client(session, OURS)
    ours, foreign = await _skill(session, OURS, "ours"), await _skill(session, THEIRS, "theirs")
    await session.execute(
        client_skills.insert(),
        [
            {"client_id": client.id, "skill_id": ours.id},
            {"client_id": client.id, "skill_id": foreign.id},
        ],
    )
    await session.commit()
    session.expunge_all()

    workspace_id = await ClientRepository.locate_workspace(session, client.id, ["ws-a", "ws-b"])
    ctx = UserContext(user_id="user-a", workspace_id=workspace_id)
    resolved = await ClientRepository(session, ctx).get_by_id(client.id)

    assert [s.id for s in resolved.skills] == [ours.id]


async def test_clients_rest_handler_refuses_a_foreign_mcp_instance(session):
    client = await _client(session, OURS)
    foreign = await _instance(session, THEIRS)

    with pytest.raises(NotFoundError):
        await clients_router.add_mcp_instance_to_client(
            client.id,
            clients_router.McpInstanceAssociationBody(id=str(foreign.id)),
            OURS,
            _clients(session),
        )


async def test_clients_toolset_refuses_a_foreign_skill(toolset_session):
    client = await _client(toolset_session, OURS)
    foreign = await _skill(toolset_session, THEIRS)

    with pytest.raises(NotFoundError):
        await ClientsToolset().add_skill(client_id=str(client.id), skill_id=str(foreign.id))


# --- agents -------------------------------------------------------------------


class _AllowAllAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _NullBroker:
    async def publish(self, _event) -> None:
        pass


def _agents(session, ctx=OURS) -> AgentService:
    return AgentService(RepositoryFactory(session, ctx), _NullBroker(), _AllowAllAuthz())


async def test_agent_create_refuses_a_foreign_skill_and_creates_nothing(session):
    foreign = await _skill(session, THEIRS)

    with pytest.raises(NotFoundError):
        await _agents(session).create_agent(AgentCreate(name="writer", tools=[], skill_ids=[foreign.id]))

    assert (await session.execute(select(Agent))).scalars().all() == []


async def test_agent_update_refuses_a_foreign_skill_and_keeps_its_skills(session):
    ours = await _skill(session, OURS)
    agent = await _agents(session).create_agent(AgentCreate(name="writer", tools=[], skill_ids=[ours.id]))
    foreign = await _skill(session, THEIRS)

    with pytest.raises(NotFoundError):
        await _agents(session).update_agent(agent.id, AgentUpdate(skill_ids=[foreign.id]))

    assert await _links(session, agent_skills_table, "agent_id", agent.id) >= {str(ours.id)}
    assert str(foreign.id) not in await _links(session, agent_skills_table, "agent_id", agent.id)


async def test_agent_skills_read_hides_a_foreign_skill_already_linked(session):
    agent = await _agent(session, OURS)
    ours, foreign = await _skill(session, OURS, "ours"), await _skill(session, THEIRS, "theirs")
    for skill in (ours, foreign):
        await session.execute(
            agent_skills_table.insert().values(agent_id=agent.id, skill_id=skill.id)
        )
    await session.commit()
    session.expunge_all()

    loaded = await _agents(session).get_with_skills(agent.id)

    assert [s.id for s in loaded.skills] == [ours.id]


# --- skill members ------------------------------------------------------------


def _skills(session, ctx=OURS) -> SkillService:
    return SkillService(RepositoryFactory(session, ctx), ctx)


async def test_skill_bundle_refuses_a_foreign_child(session):
    parent = await _skill(session, OURS, "bundle")
    foreign = await _skill(session, THEIRS)

    with pytest.raises(NotFoundError):
        await _skills(session).add_member(parent.id, foreign.id)

    assert await _links(session, skill_members_table, "parent_skill_id", parent.id) == set()


async def test_foreign_skill_bundle_is_not_found(session):
    theirs = await _skill(session, THEIRS, "bundle")
    ours = await _skill(session, OURS)

    with pytest.raises(NotFoundError):
        await _skills(session).add_member(theirs.id, ours.id)
    with pytest.raises(NotFoundError):
        await _skills(session).get_members(theirs.id)


async def test_skill_bundle_links_and_lists_its_own_workspace_child(session):
    parent = await _skill(session, OURS, "bundle")
    child = await _skill(session, OURS, "child")
    foreign = await _skill(session, THEIRS, "theirs")
    await _skills(session).add_member(parent.id, child.id)
    await session.execute(
        skill_members_table.insert().values(
            parent_skill_id=parent.id, child_skill_id=foreign.id, order=1, is_required=True
        )
    )
    await session.commit()

    members = await _skills(session).get_members(parent.id)

    assert [UUID(str(m.child_skill_id)) for m in members] == [child.id]
