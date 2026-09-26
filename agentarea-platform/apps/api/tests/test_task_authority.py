"""An invited member does not write into somebody else's run.

This was the first question asked of the authorization work and the last one it
answered. Every task-write endpoint declared
``unrestricted("workspace member; the workspace-scoped repository is the
boundary")`` -- true, and the wrong boundary: an invited member is on the same
side of the workspace column as the person whose conversation they would be
answering.

Starting a task stays member-level; you use an agent you can see. Acting on a
run that already exists belongs to whoever started it, or to a workspace admin,
who has to be able to stop something spending the workspace's money.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.v1 import agents_tasks
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

WORKSPACE = "ws-acme"
OWNER = "user-who-started-it"
INTRUDER = "user-invited-yesterday"
AGENT_ID = uuid4()
TASK_ID = uuid4()


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _app(caller: UserContext) -> tuple[FastAPI, AsyncMock]:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1/workspaces/{workspace}")

    task_service = AsyncMock()
    task_service.get_task.return_value = SimpleNamespace(
        id=TASK_ID, agent_id=AGENT_ID, user_id=OWNER, execution_id=None, status="running"
    )
    agent_service = AsyncMock()
    agent_service.get.return_value = SimpleNamespace(id=AGENT_ID, name="Helper")
    workflow_service = AsyncMock()

    app.dependency_overrides[agents_tasks.get_task_service] = lambda: task_service
    app.dependency_overrides[agents_tasks.get_agent_service] = lambda: agent_service
    app.dependency_overrides[agents_tasks.get_temporal_workflow_service] = lambda: workflow_service
    app.dependency_overrides[get_user_context] = lambda: caller
    return app, workflow_service


@pytest_asyncio.fixture
async def intruder():
    app, workflow = _app(UserContext(user_id=INTRUDER, workspace_id=WORKSPACE, admin_workspaces=[]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, workflow


@pytest_asyncio.fixture
async def owner():
    app, workflow = _app(UserContext(user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, workflow


ACTIONS = [
    ("post", f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/pause", None),
    ("post", f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/resume", None),
    ("delete", f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}", None),
    ("post", f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/command", {"command": "stop"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ACTIONS)
@pytest.mark.asyncio
async def test_a_member_cannot_act_on_a_run_they_did_not_start(intruder, method, path, body):
    client, workflow = intruder

    response = await getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
    assert not workflow.method_calls, "the guard must run before the workflow is signalled"


@pytest.mark.parametrize(("method", "path", "body"), ACTIONS)
@pytest.mark.asyncio
async def test_the_person_who_started_it_is_not_locked_out(owner, method, path, body):
    client, _ = owner

    response = await getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code != 403, f"{method} {path} -> {response.text}"


@pytest.mark.asyncio
async def test_a_workspace_admin_can_stop_a_run_that_is_not_theirs():
    """Whoever pays for the workspace has to be able to stop what is spending it."""
    app, _workflow = _app(
        UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/pause")

    assert response.status_code != 403, response.text
