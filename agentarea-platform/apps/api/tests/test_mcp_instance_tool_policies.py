"""The connection Tools page reads each tool's default beside the PDP's verdict on it.

The default is the one rule the page writes; the verdict is every workspace rule
together. They part when another rule also governs the tool, and the page can
only say so if the endpoint tells them apart.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.v1 import mcp_server_instances
from agentarea_api.api.deps.services import get_mcp_server_instance_service
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import register_singleton
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

WORKSPACE = "workspace-a"
INSTANCE_ID = uuid4()
INSTANCE_NAME = "Mailer"
TOOLS = ["send", "read"]


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[BaseModel.metadata.tables[PolicyRuleORM.__tablename__]]
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _register_authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


class _InstanceService:
    def __init__(self):
        self.instance = SimpleNamespace(
            id=INSTANCE_ID,
            name=INSTANCE_NAME,
            get_available_tools=lambda: [{"name": name} for name in TOOLS],
        )

    async def get(self, instance_id: UUID):
        return self.instance if instance_id == INSTANCE_ID else None

    async def list(self):
        return [self.instance]


def _member() -> UserContext:
    return UserContext(user_id="user-member", workspace_id=WORKSPACE)


def _app_for(session: AsyncSession, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(mcp_server_instances.router, prefix="/v1/workspaces/{workspace}")

    async def override_session():
        yield session

    app.dependency_overrides[mcp_server_instances.get_db_session] = override_session
    app.dependency_overrides[get_user_context] = lambda: context
    app.dependency_overrides[get_mcp_server_instance_service] = _InstanceService
    return app


async def _seed(session: AsyncSession, *rules: tuple[str, PolicyEffect, dict]) -> None:
    repository = PolicyRuleRepository(session, _member())
    for target, effect, params in rules:
        await repository.create(
            PolicyRule(
                subject_type=PolicySubjectType.WORKSPACE,
                subject_id=WORKSPACE,
                target=target,
                effect=effect,
                params=params,
            )
        )


async def _tool_policies(session: AsyncSession, instance_id: UUID = INSTANCE_ID):
    transport = ASGITransport(app=_app_for(session, _member()))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/v1/workspaces/acme/mcp-server-instances/{instance_id}/tool-policies"
        )


def _by_name(response) -> dict[str, dict]:
    assert response.status_code == 200, response.text
    return {tool["name"]: tool for tool in response.json()["tools"]}


async def test_the_pages_own_rule_is_the_default_and_the_verdict(session_factory):
    async with session_factory() as session:
        await _seed(session, (f"tool:mcp:{INSTANCE_ID}:send", PolicyEffect.DENY, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["send"] == {
        "name": "send",
        "default": "deny",
        "effective": "deny",
        "reason": None,
    }
    assert tools["read"] == {
        "name": "read",
        "default": "allow",
        "effective": "allow",
        "reason": None,
    }


async def test_a_bare_name_deny_is_stricter_than_the_default(session_factory):
    async with session_factory() as session:
        await _seed(session, ("tool:send", PolicyEffect.DENY, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["send"]["default"] == "allow"
    assert tools["send"]["effective"] == "deny"
    assert "denied by policy" in tools["send"]["reason"]
    assert tools["read"]["effective"] == "allow"


async def test_a_rule_naming_the_server_or_the_agent_facing_name_counts(session_factory):
    async with session_factory() as session:
        await _seed(
            session,
            (f"tool:mcp:{INSTANCE_NAME}:send", PolicyEffect.APPROVAL, {}),
            ("tool:mcp__mailer__read", PolicyEffect.DENY, {}),
        )
        tools = _by_name(await _tool_policies(session))

    assert tools["send"]["effective"] == "approval"
    assert tools["read"]["effective"] == "deny"


async def test_a_workspace_allowlist_elsewhere_denies_these_tools(session_factory):
    async with session_factory() as session:
        await _seed(session, ("tool:web_search", PolicyEffect.ALLOW, {}))
        tools = _by_name(await _tool_policies(session))

    for name in TOOLS:
        assert tools[name]["default"] == "allow"
        assert tools[name]["effective"] == "deny"
        assert "allowlist" in tools[name]["reason"]


async def test_an_approval_with_approvers_is_not_the_pages_default(session_factory):
    async with session_factory() as session:
        await _seed(
            session,
            (
                f"tool:mcp:{INSTANCE_ID}:send",
                PolicyEffect.APPROVAL,
                {"approvers": ["user:alice"]},
            ),
        )
        tools = _by_name(await _tool_policies(session))

    assert tools["send"]["default"] == "allow"
    assert tools["send"]["effective"] == "approval"
    assert tools["send"]["reason"] is not None


async def test_an_unknown_connection_is_not_found(session_factory):
    async with session_factory() as session:
        response = await _tool_policies(session, uuid4())

    assert response.status_code == 404


async def test_a_member_who_does_not_administer_the_workspace_may_read_it(session_factory):
    """Like the effective-policy preview: the verdict is the member's own to see."""
    async with session_factory() as session:
        await _seed(session, (f"tool:mcp:{INSTANCE_ID}:send", PolicyEffect.APPROVAL, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["send"]["default"] == "approval"


async def test_a_bare_name_allow_does_not_admit_this_servers_tool(session_factory):
    async with session_factory() as session:
        await _seed(session, ("tool:send", PolicyEffect.ALLOW, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["send"]["effective"] == "deny"
    assert "allowlist" in tools["send"]["reason"]


async def test_an_allow_naming_the_connection_by_name_does_not_admit_its_tool(session_factory):
    # Another connection may carry the same name; only the id names this one.
    async with session_factory() as session:
        await _seed(
            session,
            (f"tool:mcp:{INSTANCE_NAME}:send", PolicyEffect.ALLOW, {}),
            ("tool:mcp__mailer__send", PolicyEffect.ALLOW, {}),
            (f"tool:mcp:{INSTANCE_ID}:read", PolicyEffect.ALLOW, {}),
        )
        tools = _by_name(await _tool_policies(session))

    assert tools["send"]["effective"] == "deny"
    assert tools["read"]["effective"] == "allow"


async def test_every_connections_verdicts_come_in_one_read(session_factory):
    """The agent editor shows each attached server's workspace verdicts without a call per server."""
    async with session_factory() as session:
        await _seed(session, (f"tool:mcp:{INSTANCE_ID}:send", PolicyEffect.DENY, {}))
        transport = ASGITransport(app=_app_for(session, _member()))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/workspaces/acme/mcp-server-instances/tool-policies")

    assert response.status_code == 200, response.text
    [instance] = response.json()["instances"]
    assert instance["instance_id"] == str(INSTANCE_ID)
    tools = {tool["name"]: tool for tool in instance["tools"]}
    assert tools["send"]["effective"] == "deny"
    assert tools["read"]["effective"] == "allow"
