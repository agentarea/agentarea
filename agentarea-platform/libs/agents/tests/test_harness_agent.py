"""A task given to a harness client itself runs as the one agent that stands for it."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService, InvalidClientError
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_mcp.application import client_service
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


@pytest.fixture
def runners(monkeypatch) -> dict:
    """The runner clients the caller may use, by id."""
    usable: dict = {}

    async def usable_runner_client(_repository_factory, client_id):
        return usable.get(client_id)

    monkeypatch.setattr(client_service, "usable_runner_client", usable_runner_client)
    return usable


class _AllowAllAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _Broker:
    async def publish(self, event) -> None:
        pass


class _Catalog:
    async def list_items(self):
        return []


@pytest.fixture
async def session():
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
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


def _service(session) -> AgentService:
    context = UserContext(user_id="user-a", workspace_id="ws-a")
    service = AgentService(RepositoryFactory(session, context), _Broker(), _AllowAllAuthz())
    service._get_catalog_repository = lambda: _Catalog()  # type: ignore[method-assign]
    return service


async def test_the_harness_agent_is_made_once_and_runs_on_the_client(session, runners):
    client = SimpleNamespace(id=uuid4(), name="codex-xorek", kind="codex")
    runners[client.id] = client
    service = _service(session)

    first = await service.harness_agent(client.id)
    again = await service.harness_agent(client.id)

    assert again.id == first.id
    assert first.client_id == client.id
    assert first.harness_client_id == client.id
    assert first.name == "codex-xorek"
    assert not first.instruction


async def test_the_harness_agent_is_not_among_the_workspace_agents(session, runners):
    client = SimpleNamespace(id=uuid4(), name="codex-xorek", kind="codex")
    runners[client.id] = client
    service = _service(session)

    harness = await service.harness_agent(client.id)

    assert harness.id not in {agent.id for agent in await service.list()}
    assert await service.get(harness.id) is not None


async def test_a_client_that_runs_no_agents_has_no_harness_agent(session, runners):
    with pytest.raises(InvalidClientError):
        await _service(session).harness_agent(uuid4())
