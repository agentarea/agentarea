"""Archiving an agent hides it from the working set but keeps it for its runs."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_common.agent_status import AgentArchivedError, AgentStatus
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


class _AllowAllAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _RecordingBroker:
    def __init__(self):
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)


class _Catalog:
    def __init__(self, items=()):
        self._items = list(items)

    async def list_items(self):
        return list(self._items)

    async def get_item(self, item_id):
        return next((i for i in self._items if i.id == item_id), None)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    Agent.__table__,
                    Skill.__table__,
                    agent_skills_table,
                    PolicyRuleORM.__table__,
                    AuditEventORM.__table__,
                ],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _service(session, catalog=None) -> tuple[AgentService, _RecordingBroker]:
    broker = _RecordingBroker()
    context = UserContext(user_id="user-a", workspace_id="ws-a")
    service = AgentService(RepositoryFactory(session, context), broker, _AllowAllAuthz())
    service._get_catalog_repository = lambda: catalog or _Catalog()  # type: ignore[method-assign]
    return service, broker


async def test_an_archived_agent_stays_readable_by_id_and_keeps_its_grants(
    session_factory, graph
):
    async with session_factory() as session:
        service, _ = _service(session)
        agent = await service.create_agent(AgentCreate(name="Сводка дня", tools=[]))
        grants = [t for t in graph.recorded if t.object == str(agent.id)]
        assert grants

        assert await service.archive_agent(agent.id) is True

        archived = await service.get(agent.id)
        assert archived is not None
        assert archived.status == AgentStatus.ARCHIVED
        assert archived.name == "Сводка дня"
        assert [t for t in graph.recorded if t.object == str(agent.id)] == grants


async def test_an_archived_agent_leaves_the_list_and_comes_back_on_restore(session_factory):
    async with session_factory() as session:
        service, _ = _service(session)
        kept = await service.create_agent(AgentCreate(name="Остаётся", tools=[]))
        gone = await service.create_agent(AgentCreate(name="В архив", tools=[]))

        await service.archive_agent(gone.id)
        assert [a.id for a in await service.list()] == [kept.id]

        assert await service.restore_agent(gone.id) is True
        restored = await service.get(gone.id)
        assert restored is not None and restored.status == AgentStatus.ACTIVE
        assert {a.id for a in await service.list()} == {kept.id, gone.id}


async def test_archive_and_restore_are_published(session_factory):
    async with session_factory() as session:
        service, broker = _service(session)
        agent = await service.create_agent(AgentCreate(name="a", tools=[]))
        broker.events.clear()

        await service.archive_agent(agent.id)
        await service.restore_agent(agent.id)

        assert [type(e).__name__ for e in broker.events] == ["AgentArchived", "AgentRestored"]
        assert all(e.agent_id == agent.id for e in broker.events)


async def test_an_unknown_agent_is_neither_archived_nor_restored(session_factory):
    async with session_factory() as session:
        service, _ = _service(session)
        assert await service.archive_agent(uuid4()) is False
        assert await service.restore_agent(uuid4()) is False


async def test_an_archived_agent_cannot_be_edited_until_restored(session_factory):
    async with session_factory() as session:
        service, _ = _service(session)
        agent = await service.create_agent(AgentCreate(name="a", tools=[]))
        await service.archive_agent(agent.id)

        with pytest.raises(AgentArchivedError):
            await service.update_agent(agent.id, AgentUpdate(description="x"))

        await service.restore_agent(agent.id)
        updated = await service.update_agent(agent.id, AgentUpdate(description="x"))
        assert updated is not None and updated.description == "x"


async def test_a_new_agent_does_not_take_an_archived_agents_slug(session_factory):
    async with session_factory() as session:
        service, _ = _service(session)
        first = await service.create_agent(AgentCreate(name="Сводка", tools=[]))
        await service.archive_agent(first.id)

        second = await service.create_agent(AgentCreate(name="Сводка", tools=[]))

        assert second.slug != first.slug


async def test_adding_a_catalog_agent_again_restores_its_archived_copy(session_factory):
    item = SimpleNamespace(id=str(uuid4()))
    async with session_factory() as session:
        service, _ = _service(session, _Catalog([item]))
        fork = await service.create_agent(AgentCreate(name="Из каталога", tools=[]))
        fork.registry_item_id = item.id
        await service.update(fork)
        await service.archive_agent(fork.id)

        installed = await service.install_catalog_agent(UUID(item.id))

        assert installed is not None and installed.id == fork.id
        assert installed.status == AgentStatus.ACTIVE


async def test_editing_a_catalog_agent_whose_copy_is_archived_makes_no_second_copy(
    session_factory,
):
    item = SimpleNamespace(id=str(uuid4()), version=None, installed_version=None)
    async with session_factory() as session:
        service, _ = _service(session, _Catalog([item]))
        fork = await service.create_agent(AgentCreate(name="Из каталога", tools=[]))
        fork.registry_item_id = item.id
        await service.update(fork)
        await service.archive_agent(fork.id)

        with pytest.raises(AgentArchivedError):
            await service.update_agent(UUID(item.id), AgentUpdate(description="x"))

        assert [a.id for a in await service.list(include_archived=True)] == [fork.id]


async def test_an_archived_copy_keeps_its_catalog_item_out_of_the_offer(session_factory):
    item = SimpleNamespace(id=str(uuid4()), version=None, installed_version=None)
    async with session_factory() as session:
        service, _ = _service(session, _Catalog([item]))
        fork = await service.create_agent(AgentCreate(name="Из каталога", tools=[]))
        fork.registry_item_id = item.id
        await service.update(fork)
        await service.archive_agent(fork.id)

        assert await service.list(include_catalog=True) == []
        assert [a.id for a in await service.list(include_archived=True)] == [fork.id]
