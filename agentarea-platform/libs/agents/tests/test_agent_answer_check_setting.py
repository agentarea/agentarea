"""An agent carries its own answer check setting; null leaves it off."""

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def _graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


class _AllowAllAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _NullBroker:
    async def publish(self, _event) -> None:
        pass


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


async def test_the_setting_is_stored_changed_and_cleared(session_factory):
    async with session_factory() as session:
        context = UserContext(user_id="user-a", workspace_id="ws-a")
        service = AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())
        agent = await service.create_agent(
            AgentCreate(name="Сметчик", tools=[], answer_check={"language": "ru"})
        )
        assert agent.answer_check == {"enabled": True, "language": "ru"}

        updated = await service.update_agent(
            agent.id, AgentUpdate(answer_check={"enabled": False, "language": "ru"})
        )
        assert updated is not None
        assert updated.answer_check == {"enabled": False, "language": "ru"}

        untouched = await service.update_agent(agent.id, AgentUpdate(description="x"))
        assert untouched is not None and untouched.answer_check == updated.answer_check

        cleared = await service.update_agent(agent.id, AgentUpdate(answer_check=None))
        assert cleared is not None and cleared.answer_check is None


def test_an_unknown_key_in_the_setting_is_refused():
    with pytest.raises(ValidationError):
        AgentCreate(name="a", tools=[], answer_check={"lang": "ru"})
