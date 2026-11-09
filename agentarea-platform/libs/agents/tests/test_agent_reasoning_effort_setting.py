"""An agent carries how hard its model reasons, a level or a token budget; null keeps the model's default."""

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_agents.schemas.import_export import AgentYAML
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


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "minimal", "max"])
def test_any_level_name_is_accepted(effort):
    assert AgentCreate(name="a", tools=[], reasoning_effort=effort).reasoning_effort == effort
    assert AgentUpdate(reasoning_effort=effort).reasoning_effort == effort
    assert AgentYAML(name="a", reasoning_effort=effort).reasoning_effort == effort


@pytest.mark.parametrize("value", ["HIGH", "a b", "3", 3])
def test_a_malformed_effort_is_refused(value):
    with pytest.raises(ValidationError, match="reasoning_effort"):
        AgentCreate(name="a", tools=[], reasoning_effort=value)
    with pytest.raises(ValidationError, match="reasoning_effort"):
        AgentUpdate(reasoning_effort=value)
    with pytest.raises(ValidationError, match="reasoning_effort"):
        AgentYAML(name="a", reasoning_effort=value)


@pytest.mark.parametrize("value", [0, -1, "1024", 1.5, True])
def test_a_token_budget_that_is_not_a_positive_integer_is_refused(value):
    with pytest.raises(ValidationError, match="reasoning_max_tokens"):
        AgentCreate(name="a", tools=[], reasoning_max_tokens=value)
    with pytest.raises(ValidationError, match="reasoning_max_tokens"):
        AgentUpdate(reasoning_max_tokens=value)
    with pytest.raises(ValidationError, match="reasoning_max_tokens"):
        AgentYAML(name="a", reasoning_max_tokens=value)


def test_a_token_budget_is_accepted():
    assert AgentCreate(name="a", tools=[], reasoning_max_tokens=2048).reasoning_max_tokens == 2048
    assert AgentUpdate(reasoning_max_tokens=2048).reasoning_max_tokens == 2048
    assert AgentYAML(name="a", reasoning_max_tokens=2048).reasoning_max_tokens == 2048


def test_a_level_and_a_token_budget_together_are_refused():
    with pytest.raises(ValidationError, match="not both"):
        AgentCreate(name="a", tools=[], reasoning_effort="high", reasoning_max_tokens=2048)
    with pytest.raises(ValidationError, match="not both"):
        AgentYAML(name="a", reasoning_effort="high", reasoning_max_tokens=2048)


def test_an_empty_effort_on_update_clears_the_setting():
    assert AgentUpdate.model_validate({"reasoning_effort": ""}).model_dump(exclude_unset=True) == {
        "reasoning_effort": None
    }


async def test_the_setting_is_stored_changed_and_cleared(session_factory):
    async with session_factory() as session:
        context = UserContext(user_id="user-a", workspace_id="ws-a")
        service = AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())
        agent = await service.create_agent(
            AgentCreate(name="Thinker", tools=[], reasoning_effort="low")
        )
        assert agent.reasoning_effort == "low"

        updated = await service.update_agent(agent.id, AgentUpdate(reasoning_effort="high"))
        assert updated is not None and updated.reasoning_effort == "high"

        untouched = await service.update_agent(agent.id, AgentUpdate(description="x"))
        assert untouched is not None and untouched.reasoning_effort == "high"

        cleared = await service.update_agent(agent.id, AgentUpdate(reasoning_effort=None))
        assert cleared is not None and cleared.reasoning_effort is None


async def test_an_agent_created_without_the_setting_keeps_the_model_default(session_factory):
    async with session_factory() as session:
        context = UserContext(user_id="user-a", workspace_id="ws-a")
        service = AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())
        agent = await service.create_agent(AgentCreate(name="Plain", tools=[]))
        assert agent.reasoning_effort is None


async def test_the_token_budget_is_stored_changed_and_cleared(session_factory):
    async with session_factory() as session:
        context = UserContext(user_id="user-a", workspace_id="ws-a")
        service = AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())
        agent = await service.create_agent(
            AgentCreate(name="Budgeted", tools=[], reasoning_max_tokens=1024)
        )
        assert agent.reasoning_max_tokens == 1024

        updated = await service.update_agent(agent.id, AgentUpdate(reasoning_max_tokens=4096))
        assert updated is not None and updated.reasoning_max_tokens == 4096

        untouched = await service.update_agent(agent.id, AgentUpdate(description="x"))
        assert untouched is not None and untouched.reasoning_max_tokens == 4096

        cleared = await service.update_agent(agent.id, AgentUpdate(reasoning_max_tokens=None))
        assert cleared is not None and cleared.reasoning_max_tokens is None


async def test_an_update_that_leaves_both_forms_set_is_refused(session_factory):
    async with session_factory() as session:
        context = UserContext(user_id="user-a", workspace_id="ws-a")
        service = AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())
        agent = await service.create_agent(
            AgentCreate(name="Leveled", tools=[], reasoning_effort="high")
        )

        with pytest.raises(ValueError, match="not both"):
            await service.update_agent(agent.id, AgentUpdate(reasoning_max_tokens=2048))

        switched = await service.update_agent(
            agent.id, AgentUpdate(reasoning_effort=None, reasoning_max_tokens=2048)
        )
        assert switched is not None
        assert (switched.reasoning_effort, switched.reasoning_max_tokens) == (None, 2048)
