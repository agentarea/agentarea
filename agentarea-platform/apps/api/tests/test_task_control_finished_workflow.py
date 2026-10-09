"""A workflow that has ended takes no more signals, however it ended.

Pause, resume and input refused a completed, failed or cancelled workflow with
400, but not a terminated one, which is what the executor reports for a
workflow killed from outside it. That one was signalled anyway, the signal
failed inside Temporal, and the request came back a 500.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_secret_manager
from agentarea_api.api.v1 import agents_tasks
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.workflow.executor import WorkflowStatus
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

WORKSPACE = "ws-acme"
OWNER = "user-who-started-it"
AGENT_ID = uuid4()
TASK_ID = uuid4()
BASE = f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}"


@pytest_asyncio.fixture
async def control():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1/workspaces/{workspace}")

    task_service = AsyncMock()
    task_service.get_task.return_value = SimpleNamespace(
        id=TASK_ID, agent_id=AGENT_ID, user_id=OWNER, execution_id=None, status="running"
    )
    agent_service = AsyncMock()
    agent_service.get.return_value = SimpleNamespace(id=AGENT_ID, name="Helper")
    workflow = AsyncMock()
    workflow.get_live_state.return_value = {"paused": False}

    app.dependency_overrides[agents_tasks.get_task_service] = lambda: task_service
    app.dependency_overrides[agents_tasks.get_agent_service] = lambda: agent_service
    app.dependency_overrides[agents_tasks.get_temporal_workflow_service] = lambda: workflow
    app.dependency_overrides[get_secret_manager] = lambda: AsyncMock()
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client, workflow


FINISHED = [
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
    WorkflowStatus.TERMINATED,
]


@pytest.mark.parametrize("status", FINISHED, ids=lambda s: s.value)
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/pause", None),
        ("/resume", None),
        ("/input", {"input_request_id": "req-1", "answers": {"answer": "yes"}}),
    ],
)
async def test_a_finished_workflow_is_not_signalled(control, status, path, body) -> None:
    client, workflow = control
    workflow.get_workflow_status.return_value = {"status": status.value}

    response = await client.post(BASE + path, **({"json": body} if body else {}))

    assert response.status_code == 400, response.text
    assert status.value in response.json()["detail"]
    workflow.pause_task.assert_not_awaited()
    workflow.resume_task.assert_not_awaited()


async def test_a_running_workflow_is_still_paused(control) -> None:
    client, workflow = control
    workflow.get_workflow_status.return_value = {"status": WorkflowStatus.RUNNING.value}
    workflow.pause_task.return_value = True

    response = await client.post(f"{BASE}/pause")

    assert response.status_code == 200, response.text
    workflow.pause_task.assert_awaited_once()
