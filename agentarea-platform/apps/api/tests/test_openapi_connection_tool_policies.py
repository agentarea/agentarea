"""An API connection's Tools page reads each operation's default beside the PDP's verdict.

The same contract as an MCP connection's (test_mcp_instance_tool_policies.py), over
the names a run gives an operation: ``openapi:<connection id>:<tool>`` may allow
it, its bare tool name may only narrow.
"""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from agentarea_api.api.deps.services import get_db_session, get_openapi_connection_service
from agentarea_api.api.v1 import openapi_connections
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
CONNECTION_ID = uuid4()
# A spec's operation names carry characters a tool name cannot; a run calls this
# one ``issues.create``'s slug, ``issues_create``.
TOOLS = ["issues.create", "list_issues"]


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


class _ConnectionService:
    async def get_connection(self, connection_id: UUID):
        if connection_id != CONNECTION_ID:
            return None
        return SimpleNamespace(id=CONNECTION_ID, available_tools=[{"name": name} for name in TOOLS])


def _member() -> UserContext:
    return UserContext(user_id="user-member", workspace_id=WORKSPACE)


def _app_for(session: AsyncSession) -> FastAPI:
    app = FastAPI()
    app.include_router(openapi_connections.router, prefix="/v1/workspaces/{workspace}")

    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_user_context] = _member
    app.dependency_overrides[get_openapi_connection_service] = _ConnectionService
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


async def _tool_policies(session: AsyncSession, connection_id: UUID = CONNECTION_ID):
    transport = ASGITransport(app=_app_for(session))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(
            f"/v1/workspaces/acme/openapi-connections/{connection_id}/tool-policies"
        )


def _by_name(response) -> dict[str, dict]:
    assert response.status_code == 200, response.text
    return {tool["name"]: tool for tool in response.json()["tools"]}


async def test_the_rule_on_the_operations_run_name_is_its_default(session_factory):
    async with session_factory() as session:
        await _seed(
            session, (f"tool:openapi:{CONNECTION_ID}:issues_create", PolicyEffect.APPROVAL, {})
        )
        tools = _by_name(await _tool_policies(session))

    assert tools["issues.create"] == {
        "name": "issues.create",
        "default": "approval",
        "effective": "approval",
        "reason": None,
    }
    assert tools["list_issues"] == {
        "name": "list_issues",
        "default": "allow",
        "effective": "allow",
        "reason": None,
    }


async def test_a_bare_name_deny_is_stricter_than_the_default(session_factory):
    async with session_factory() as session:
        await _seed(session, ("tool:list_issues", PolicyEffect.DENY, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["list_issues"]["default"] == "allow"
    assert tools["list_issues"]["effective"] == "deny"
    assert "denied by policy" in tools["list_issues"]["reason"]


async def test_a_bare_name_allow_does_not_admit_the_operation(session_factory):
    async with session_factory() as session:
        await _seed(session, ("tool:list_issues", PolicyEffect.ALLOW, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["list_issues"]["effective"] == "deny"
    assert "allowlist" in tools["list_issues"]["reason"]


async def test_an_allow_on_the_connections_id_admits_the_operation(session_factory):
    async with session_factory() as session:
        await _seed(session, (f"tool:openapi:{CONNECTION_ID}:list_issues", PolicyEffect.ALLOW, {}))
        tools = _by_name(await _tool_policies(session))

    assert tools["list_issues"]["effective"] == "allow"
    assert tools["issues.create"]["effective"] == "deny"


async def test_an_unknown_connection_is_not_found(session_factory):
    async with session_factory() as session:
        response = await _tool_policies(session, uuid4())

    assert response.status_code == 404
