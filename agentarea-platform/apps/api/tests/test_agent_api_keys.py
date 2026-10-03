"""An agent's key reaches that one agent over A2A, and nothing else.

It is the key a workspace hands to a caller outside it: the caller can task
the agent, but the key opens no workspace, no other agent and no REST route.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_api.api.deps.services import get_audit_service, get_db_session
from agentarea_api.api.v1.api_keys import router
from agentarea_common.auth import dependencies
from agentarea_common.auth.access import authorize_agent_action
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.dependencies import _validate_api_key, get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import get_container
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_common.workspaces import Workspace
from agentarea_mcp.domain.auth_models import APIKey
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

OWNER = "owner-user"
WORKSPACE = "ws-acme"
MEMBER = UserContext(user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])


@pytest.fixture(autouse=True)
def _graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


@pytest.fixture(autouse=True)
def _authz():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    Workspace.__table__,
                    APIKey.__table__,
                    Agent.__table__,
                    Skill.__table__,
                    agent_skills_table,
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(Workspace(id=WORKSPACE, slug="acme", name="Acme", owner_user_id=OWNER))
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _agent(session_factory) -> Agent:
    async with session_factory() as session:
        name = f"agent-{uuid4().hex[:6]}"
        agent = Agent(
            name=name,
            slug=name,
            description="",
            instruction="",
            workspace_id=WORKSPACE,
            created_by=OWNER,
        )
        session.add(agent)
        await session.commit()
        return agent


def _client(session_factory, audit: AsyncMock | None = None) -> TestClient:
    async def session():
        async with session_factory() as s:
            yield s

    app = FastAPI()
    app.include_router(router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_db_session] = session
    # audit_events is Postgres-typed (JSONB, INET); SQLite cannot hold it.
    app.dependency_overrides[get_audit_service] = lambda: audit or AsyncMock()
    app.dependency_overrides[get_user_context] = lambda: MEMBER
    return TestClient(app)


async def _authenticate(session_factory, token: str) -> UserPrincipal | None:
    database = SimpleNamespace(async_session_factory=session_factory)
    with patch("agentarea_common.config.get_database", return_value=database):
        return await _validate_api_key(token, MagicMock())


async def test_a_key_bound_to_an_agent_authenticates_as_its_issuer_on_that_agent(session_factory):
    agent = await _agent(session_factory)
    created = _client(session_factory).post(
        "/v1/workspaces/acme/api-keys/", json={"name": "for personal", "agent_id": str(agent.id)}
    )
    assert created.status_code == 201, created.text
    assert created.json()["agent_id"] == str(agent.id)

    principal = await _authenticate(session_factory, created.json()["token"])

    assert principal is not None
    assert (principal.user_id, principal.bound_workspace_id, principal.bound_agent_id) == (
        OWNER,
        WORKSPACE,
        str(agent.id),
    )


async def test_a_key_cannot_be_bound_to_an_agent_outside_the_workspace(session_factory):
    audit = AsyncMock()
    response = _client(session_factory, audit).post(
        "/v1/workspaces/acme/api-keys/", json={"name": "x", "agent_id": str(uuid4())}
    )

    assert response.status_code == 404, response.text
    audit.record.assert_not_awaited()


async def test_a_created_key_is_audited_by_name_and_never_by_token(session_factory):
    audit = AsyncMock()
    created = _client(session_factory, audit).post(
        "/v1/workspaces/acme/api-keys/", json={"name": "ci deploy"}
    )

    assert created.status_code == 201, created.text
    audit.record.assert_awaited_once()
    action, resource_type, resource_id = audit.record.await_args.args
    metadata = audit.record.await_args.kwargs["event_metadata"]
    assert (action, resource_type, str(resource_id)) == (
        "api_key.create",
        "api_key",
        created.json()["id"],
    )
    assert metadata["resource_name"] == "ci deploy"
    assert metadata["token_prefix"] == created.json()["token_prefix"]
    assert created.json()["token"] not in str(audit.record.await_args)


async def test_the_keys_of_one_agent_are_listed_apart(session_factory):
    agent = await _agent(session_factory)
    client = _client(session_factory)
    client.post("/v1/workspaces/acme/api-keys/", json={"name": "workspace key"})
    client.post(
        "/v1/workspaces/acme/api-keys/", json={"name": "agent key", "agent_id": str(agent.id)}
    )

    listed = client.get(f"/v1/workspaces/acme/api-keys/?agent_id={agent.id}")

    assert listed.status_code == 200, listed.text
    assert [k["name"] for k in listed.json()] == ["agent key"]


def _agent_key(agent_id: str) -> UserPrincipal:
    return UserPrincipal(user_id=OWNER, bound_workspace_id=WORKSPACE, bound_agent_id=agent_id)


async def test_an_agents_key_may_act_on_that_agent():
    agent_id = str(uuid4())

    decision = await authorize_agent_action(
        _agent_key(agent_id), "agent:execute", agent_workspace_id=WORKSPACE, agent_id=agent_id
    )

    assert decision.allowed


async def test_an_agents_key_may_not_act_on_another_agent_of_its_workspace():
    principal = _agent_key(str(uuid4()))
    principal.accessible_workspaces = [WORKSPACE]

    decision = await authorize_agent_action(
        principal, "agent:execute", agent_workspace_id=WORKSPACE, agent_id=str(uuid4())
    )

    assert not decision.allowed


def _request(path_params: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.state = SimpleNamespace()
    request.path_params = path_params or {}
    return request


async def test_an_agents_key_acts_in_its_workspace_on_a_request_bound_to_its_agent():
    agent_id = str(uuid4())
    request = _request()
    dependencies.bind_request_workspace(request, WORKSPACE, "acme", agent_id=agent_id)

    context = await dependencies.get_user_context(request, _agent_key(agent_id))

    assert (context.user_id, context.workspace_id) == (OWNER, WORKSPACE)
    assert context.admin_workspaces == []


async def test_an_agents_key_is_refused_on_a_request_bound_to_another_agent():
    request = _request()
    dependencies.bind_request_workspace(request, WORKSPACE, "acme", agent_id=str(uuid4()))

    with pytest.raises(HTTPException) as refused:
        await dependencies.get_user_context(request, _agent_key(str(uuid4())))

    assert refused.value.status_code == 403


async def test_an_agents_key_is_refused_by_a_workspace_route():
    with pytest.raises(HTTPException) as refused:
        await dependencies.get_user_context(
            _request({"workspace": "acme"}), _agent_key(str(uuid4()))
        )

    assert refused.value.status_code == 403


async def test_an_agents_key_is_refused_by_a_route_that_names_no_workspace():
    with pytest.raises(HTTPException) as refused:
        await dependencies.get_principal(_agent_key(str(uuid4())))

    assert refused.value.status_code == 403
