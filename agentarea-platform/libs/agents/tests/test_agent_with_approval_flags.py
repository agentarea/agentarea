"""Saving an agent's tools as with_approval_flags returns them leaves its approvals as they are.

A tool sent without its flag reads as unticked, and unticking removes the rule
behind it, an admin's own included. A writer that never shows the toggle, such
as a bundle redeploy, saves the tools with the flags the rules set.
"""

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_agents.schemas.import_export import TOOL_CONFIG_ADAPTER
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.di.container import register_singleton
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from agentarea_mcp.domain.auth_models import MCPAuthConfig
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

CONTEXT = UserContext(user_id="user-a", workspace_id="ws-a", admin_workspaces=["ws-a"])


@pytest.fixture(autouse=True)
def _graph(monkeypatch):
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    return install_graph_ownership_stub(monkeypatch)


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
                    MCPAuthConfig.__table__,
                    MCPServerInstance.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


class _Authz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True

    async def can_administer_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _NullBroker:
    async def publish(self, _event) -> None:
        pass


async def _rule_targets(session: AsyncSession, agent_id) -> list[str]:
    rows = await session.execute(
        select(PolicyRuleORM.target).where(PolicyRuleORM.subject_id == str(agent_id))
    )
    return sorted(rows.scalars())


async def test_tools_saved_with_their_flags_keep_an_admins_approval_rule(session):
    service = AgentService(RepositoryFactory(session, CONTEXT), _NullBroker(), _Authz())
    agent = await service.create_agent(
        AgentCreate(name="lead", tools=[{"type": "code", "name": "agentarea/web"}])
    )
    await PolicyRuleRepository(session, CONTEXT).create(
        PolicyRule(
            subject_type=PolicySubjectType.AGENT,
            subject_id=str(agent.id),
            target="tool:web",
            effect=PolicyEffect.APPROVAL,
        )
    )
    tools = [{"type": "code", "name": "agentarea/web"}, {"type": "code", "name": "agentarea/shell"}]

    flagged = await service.with_approval_flags(agent.id, tools)
    await service.update_agent(
        agent.id, AgentUpdate(tools=[TOOL_CONFIG_ADAPTER.validate_python(t) for t in flagged])
    )
    assert await _rule_targets(session, agent.id) == ["tool:web"]

    await service.update_agent(
        agent.id, AgentUpdate(tools=[TOOL_CONFIG_ADAPTER.validate_python(t) for t in tools])
    )
    assert await _rule_targets(session, agent.id) == []
