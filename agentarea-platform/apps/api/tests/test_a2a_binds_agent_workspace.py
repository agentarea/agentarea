"""An A2A call acts in the agent's workspace, not the caller's.

The A2A URL names an agent, not a workspace. The route loads the agent without
workspace scoping, authorizes the caller against the agent's workspace, and
binds that workspace for the request -- so every workspace-scoped dependency
the handler builds (task service, agent service, secrets) is scoped to where
the agent lives. Before this, the task service was built for whatever
workspace the caller happened to be acting in.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from agentarea_api.api.deps.services import get_agent_service, get_secret_manager, get_task_service
from agentarea_api.api.v1 import agents_well_known
from agentarea_api.api.v1.router import a2a_v1_router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.config.database import get_read_db_session
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI

AGENT_WORKSPACE = SimpleNamespace(id="ws-agent", slug="agent-home")
AGENT_ID = uuid4()
AGENT = SimpleNamespace(
    id=AGENT_ID,
    name="helper",
    description=None,
    status="active",
    workspace_id=AGENT_WORKSPACE.id,
    tools=None,
    planning=None,
    a2ui_enabled=False,
)
RPC = f"http://t/v1/agents/{AGENT_ID}/a2a/rpc"


class _RecordingTaskService:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id

    async def get_task(self, task_id):
        return None

    async def get_task_with_workflow_status(self, task_id):
        return None


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

    async def public_agent(agent_id, session):
        return AGENT if agent_id == AGENT_ID else None

    monkeypatch.setattr(agents_well_known, "get_public_agent", public_agent)
    with (
        patch(
            "agentarea_common.auth.dependencies._owned_and_named_workspaces",
            new=AsyncMock(return_value=([], None)),
        ),
        patch(
            "agentarea_common.workspaces.lookup.load_workspace",
            new=AsyncMock(return_value=AGENT_WORKSPACE),
        ),
        patch(
            "agentarea_common.auth.dependencies._validate_api_key",
            new=AsyncMock(side_effect=lambda token, request: UserPrincipal(user_id="caller")),
        ) as validate_api_key,
    ):
        yield validate_api_key


def _app(recorded: list) -> FastAPI:
    app = FastAPI()
    app.include_router(a2a_v1_router)

    def task_service(ctx: UserContextDep) -> _RecordingTaskService:
        recorded.append(ctx)
        return _RecordingTaskService(ctx.workspace_id)

    app.dependency_overrides[get_read_db_session] = lambda: None
    app.dependency_overrides[get_task_service] = task_service
    app.dependency_overrides[get_agent_service] = lambda: SimpleNamespace()
    app.dependency_overrides[get_secret_manager] = lambda: SimpleNamespace()
    return app


async def _get_task(app: FastAPI) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        return await client.post(
            RPC,
            json={"jsonrpc": "2.0", "id": "r", "method": "GetTask", "params": {"id": str(uuid4())}},
            headers={"A2A-Version": "1.0", "Authorization": "Bearer aat_caller-token"},
        )


@pytest.mark.asyncio
async def test_a_member_of_the_agent_workspace_acts_in_it():
    recorded: list = []
    with patch(
        "agentarea_common.auth.dependencies._member_workspace_ids",
        new=AsyncMock(return_value=[AGENT_WORKSPACE.id]),
    ):
        response = await _get_task(_app(recorded))

    assert response.status_code == 200, response.text
    assert [ctx.workspace_id for ctx in recorded] == [AGENT_WORKSPACE.id]
    assert recorded[0].workspace_slug == AGENT_WORKSPACE.slug


@pytest.mark.asyncio
async def test_the_caller_is_authenticated_once_per_request(_world):
    """The binder and get_user_context share one authentication: an API key is
    looked up, and its access count bumped, once."""
    with patch(
        "agentarea_common.auth.dependencies._member_workspace_ids",
        new=AsyncMock(return_value=[AGENT_WORKSPACE.id]),
    ):
        response = await _get_task(_app([]))

    assert response.status_code == 200, response.text
    assert _world.await_count == 1


@pytest.mark.asyncio
async def test_a_caller_outside_the_agent_workspace_is_refused():
    recorded: list = []
    with patch(
        "agentarea_common.auth.dependencies._member_workspace_ids",
        new=AsyncMock(return_value=["ws-somewhere-else"]),
    ):
        response = await _get_task(_app(recorded))

    assert response.status_code == 403
    assert recorded == []


@pytest.mark.asyncio
async def test_an_unknown_agent_is_not_found():
    app = _app([])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            f"http://t/v1/agents/{uuid4()}/a2a/rpc",
            json={"jsonrpc": "2.0", "id": "r", "method": "GetTask", "params": {"id": "x"}},
            headers={"A2A-Version": "1.0", "Authorization": "Bearer aat_caller-token"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_malformed_agent_id_is_not_found_rather_than_a_server_error():
    app = _app([])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            "http://t/v1/agents/0/a2a/rpc",
            json={"jsonrpc": "2.0", "id": "r", "method": "GetTask", "params": {"id": "x"}},
            headers={"A2A-Version": "1.0", "Authorization": "Bearer aat_caller-token"},
        )

    assert response.status_code == 404
