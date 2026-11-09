"""An agent's MCP tool is stored with its connection's id, the only reference the runtime reads.

Connection names are not unique and any member picks them. A tool written with
a name is bound to the one connection carrying it when that connection is the
caller's or the platform's; a name several carry, or only someone else's, is
refused instead of resolved.
"""

from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService, InvalidMcpToolError
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_mcp.domain.auth_models import MCPAuthConfig
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture(autouse=True)
def _graph(monkeypatch):
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


def _service(session: AsyncSession) -> AgentService:
    context = UserContext(user_id="user-a", workspace_id="ws-a", admin_workspaces=["ws-a"])
    return AgentService(RepositoryFactory(session, context), _NullBroker(), _Authz())


async def _connection(
    session: AsyncSession,
    name: str,
    workspace: str = "ws-a",
    created_by: str = "user-a",
    managed_by: str | None = None,
) -> str:
    instance = MCPServerInstance(
        id=uuid4(),
        workspace_id=workspace,
        created_by=created_by,
        managed_by=managed_by,
        name=name,
        server_spec_id=str(uuid4()),
        transport="url",
        json_spec={},
    )
    session.add(instance)
    await session.flush()
    return str(instance.id)


def _mcp(ref: str, *tools: str, approval: bool = False) -> dict:
    allowed = [{"tool_name": t, "requires_user_confirmation": approval} for t in tools]
    return {"type": "mcp", "name": ref, "settings": {"allowed_tools": allowed or None}}


def _create(*tools: dict) -> AgentCreate:
    return AgentCreate(name="lead", description="", instruction="", tools=list(tools))


async def test_a_name_one_connection_carries_is_stored_as_its_id(session):
    connection = await _connection(session, "github")
    await _connection(session, "github", workspace="ws-b")

    agent = await _service(session).create_agent(_create(_mcp("github")))

    assert agent.tools[0]["name"] == connection


async def test_a_name_two_connections_carry_is_refused(session):
    await _connection(session, "github")
    await _connection(session, "github")

    with pytest.raises(InvalidMcpToolError, match="2 MCP connections here are named 'github'"):
        await _service(session).create_agent(_create(_mcp("github")))


async def test_an_id_is_kept_and_a_name_no_connection_carries_waits_to_be_connected(session):
    connection = await _connection(session, "github")
    await _connection(session, "github")

    agent = await _service(session).create_agent(_create(_mcp(connection), _mcp("linear")))

    assert [tool["name"] for tool in agent.tools] == [connection, "linear"]


async def test_an_approval_ticked_on_a_named_tool_targets_the_bound_connection(session):
    connection = await _connection(session, "github")

    agent = await _service(session).create_agent(_create(_mcp("github", "push", approval=True)))

    targets = (
        await session.execute(
            select(PolicyRuleORM.target).where(PolicyRuleORM.subject_id == str(agent.id))
        )
    ).scalars()
    assert list(targets) == [f"tool:mcp:{connection}:push"]


async def test_an_update_binds_a_name_too(session):
    service = _service(session)
    agent = await service.create_agent(_create())
    connection = await _connection(session, "github")

    updated = await service.update_agent(agent.id, AgentUpdate(tools=[_mcp("github")]))

    assert updated is not None
    assert updated.tools[0]["name"] == connection


async def test_a_name_only_someone_elses_connection_carries_is_refused(session):
    await _connection(session, "github", created_by="user-b")

    with pytest.raises(InvalidMcpToolError, match="added by someone else"):
        await _service(session).create_agent(_create(_mcp("github")))


async def test_a_platform_connection_binds_by_name(session):
    gateway = await _connection(session, "tools", workspace="platform", managed_by="platform")

    agent = await _service(session).create_agent(_create(_mcp("tools")))

    assert agent.tools[0]["name"] == gateway
