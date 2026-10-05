"""A paused run reads as paused, so whoever opens it next can resume it.

A pause is a signal the workflow keeps in its own state while Temporal goes on
reporting "running". The status endpoint said only "running", so after a reload
the task page offered Pause on a paused run and never Resume. The refusal of a
second pause is covered in libs/agents/tests/test_agents_tasks_control.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
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
AGENT_ID = uuid4()
TASK_ID = uuid4()
BASE = f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}"


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


@pytest.fixture(autouse=True)
def _no_artifacts(monkeypatch):
    monkeypatch.setattr(agents_tasks, "_list_task_artifact_items", AsyncMock(return_value=[]))


def _client(*, paused: bool) -> tuple[AsyncClient, AsyncMock]:
    task = SimpleNamespace(
        id=TASK_ID,
        agent_id=AGENT_ID,
        user_id=OWNER,
        execution_id=f"task-{TASK_ID}",
        status="running",
        error_message=None,
        result=None,
    )
    task_service = AsyncMock()
    task_service.get_task.return_value = task
    task_service.get_task_with_workflow_status.return_value = task
    agent_service = AsyncMock()
    agent_service.get.return_value = SimpleNamespace(id=AGENT_ID, name="Helper")
    workflow_service = AsyncMock()
    workflow_service.get_workflow_status.return_value = {
        "status": "running",
        "execution_status": "running",
    }
    workflow_service.get_live_state.return_value = {"paused": paused}

    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[agents_tasks.get_task_service] = lambda: task_service
    app.dependency_overrides[agents_tasks.get_read_task_service] = lambda: task_service
    app.dependency_overrides[agents_tasks.get_agent_service] = lambda: agent_service
    app.dependency_overrides[agents_tasks.get_temporal_workflow_service] = lambda: workflow_service
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[]
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t"), workflow_service


@pytest.mark.asyncio
@pytest.mark.parametrize("paused", [True, False])
async def test_status_reports_the_workflows_pause(paused: bool) -> None:
    client, _ = _client(paused=paused)
    async with client:
        response = await client.get(f"{BASE}/status")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "running"
    assert response.json()["paused"] is paused
