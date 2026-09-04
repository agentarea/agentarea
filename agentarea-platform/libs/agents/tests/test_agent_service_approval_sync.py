"""AgentService lifts the per-tool approval toggle into policy rules.

The toggle used to be reconciled only in the apps/api router, so agents created
through any other path (bundle install, workspace import, catalog fork) got the
flag persisted in config but no enforcing rule. These tests pin that the service
is now the single home: a ticked tool produces an agent-scoped APPROVAL rule and
the persisted config never carries the flag.
"""

from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.infrastructure.catalog_agent_repository import CatalogAgentItem
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.domain.rules import PolicyEffect, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


def _context(workspace_id: str = "ws-a") -> UserContext:
    return UserContext(user_id="user-a", workspace_id=workspace_id)


class _AllowAllAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _NullBroker:
    async def publish(self, _event) -> None:
        pass


class _NullCatalogRepo:
    async def mark_installed(self, *args, **kwargs) -> None:
        pass


def _service(session: AsyncSession, context: UserContext) -> AgentService:
    return AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())


async def _rules(session: AsyncSession, context: UserContext, agent_id) -> list:
    return await PolicyRuleRepository(session, context).list_rules(
        subject_type=PolicySubjectType.AGENT, subject_id=str(agent_id)
    )


def _code_tool(name: str, confirm: bool) -> dict:
    return {"name": name, "type": "code", "settings": {"requires_user_confirmation": confirm}}


def _mcp_tool(name: str, tool_name: str, confirm: bool) -> dict:
    return {
        "name": name,
        "type": "mcp",
        "settings": {
            "allowed_tools": [{"tool_name": tool_name, "requires_user_confirmation": confirm}]
        },
    }


async def test_create_agent_lifts_toggle_into_a_rule_and_strips_the_flag(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)

        agent = await service.create_agent(
            AgentCreate(
                name="Approver", model_id=None, tools=[_code_tool("agentarea/shell", True)]
            )
        )

        rules = await _rules(session, context, agent.id)
        assert [(r.target, r.effect) for r in rules] == [("tool:shell", PolicyEffect.APPROVAL)]
        assert agent.tools[0]["settings"].get("requires_user_confirmation") is None


async def test_create_agent_without_confirmation_writes_no_rule(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)

        agent = await service.create_agent(
            AgentCreate(
                name="Plain", model_id=None, tools=[_code_tool("agentarea/shell", False)]
            )
        )

        assert await _rules(session, context, agent.id) == []


async def test_update_agent_reconciles_the_rule_and_strips_the_flag(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)
        agent = await service.create_agent(AgentCreate(name="Editable", model_id=None))

        updated = await service.update_agent(
            agent.id,
            AgentUpdate(tools=[_mcp_tool("github", "create_issue", True)]),
        )

        rules = await _rules(session, context, agent.id)
        assert {r.target for r in rules} == {"tool:create_issue"}
        allowed = updated.tools[0]["settings"]["allowed_tools"]
        assert allowed == [{"tool_name": "create_issue"}]


async def test_update_agent_unticking_removes_the_rule(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)
        agent = await service.create_agent(
            AgentCreate(
                name="Editable", model_id=None, tools=[_code_tool("agentarea/shell", True)]
            )
        )
        assert {r.target for r in await _rules(session, context, agent.id)} == {"tool:shell"}

        await service.update_agent(
            agent.id, AgentUpdate(tools=[_code_tool("agentarea/shell", False)])
        )

        assert await _rules(session, context, agent.id) == []


async def test_fork_catalog_agent_strips_and_syncs(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)
        service._get_catalog_repository = lambda: _NullCatalogRepo()  # type: ignore[method-assign]

        item = CatalogAgentItem(
            id=str(uuid4()),
            name="Built-in Approver",
            description="desc",
            version="1",
            spec={"instruction": "do x", "tools": [_code_tool("agentarea/shell", True)]},
            installed_entity_id=None,
            installed_version=None,
        )

        agent = await service._fork_catalog_agent(item)

        rules = await _rules(session, context, agent.id)
        assert {r.target for r in rules} == {"tool:shell"}
        assert agent.tools[0]["settings"].get("requires_user_confirmation") is None
