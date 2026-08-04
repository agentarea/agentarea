"""HTTP-level tests for task policy request handling."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import agents_tasks
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_governance.domain.policies import PolicyValidationError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _task(agent_id):
    return SimpleNamespace(
        id=uuid4(),
        agent_id=agent_id,
        description="do the work",
        task_parameters={},
        status="running",
        result=None,
        error_message=None,
        created_at=datetime.now(UTC),
        execution_id="exec-1",
    )


def _app_for(task_service, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")

    async def override_task_service():
        return task_service

    async def override_user_context():
        return context

    app.dependency_overrides[agents_tasks.get_task_service] = override_task_service
    app.dependency_overrides[get_user_context] = override_user_context
    return app


def test_task_artifact_download_url_is_api_relative():
    agent_id = uuid4()
    task_id = uuid4()
    artifact_id = "art_0123456789abcdef0123456789abcdef"

    url = agents_tasks._task_artifact_download_url(agent_id, task_id, artifact_id)

    assert url == f"/v1/agents/{agent_id}/tasks/{task_id}/artifacts/files/{artifact_id}"
    assert "agentarea-backend" not in url


@pytest.mark.asyncio
async def test_task_artifact_download_rejects_anything_but_an_opaque_id():
    """Artifacts are addressed by minted id, never by workspace path.

    The id is the whole reason the route cannot be walked out of the task's
    own artifacts: a path-shaped identifier is refused before the request ever
    reaches the sandbox manager.
    """
    agent_id = uuid4()
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    task = _task(agent_id)
    task_service = SimpleNamespace(get_task=AsyncMock(return_value=task))
    app = _app_for(task_service, context)
    app.dependency_overrides[agents_tasks.get_read_task_service] = lambda: task_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/v1/agents/{agent_id}/tasks/{task.id}/artifacts/files/"
            "tasks/other-task/report.html"
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_task_sync_accepts_task_policy_and_passes_typed_payload():
    agent_id = uuid4()
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    task_service = SimpleNamespace(start_run=AsyncMock(return_value=_task(agent_id)))
    app = _app_for(task_service, context)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/v1/agents/{agent_id}/tasks/sync",
            json={
                "description": "do the work",
                "task_policy": {"budget": {"run_budget_usd": "1.25"}},
            },
        )

    assert response.status_code == 200
    payload = task_service.start_run.await_args.args[0]
    assert str(payload.task_policy.budget.run_budget_usd) == "1.25"
    assert task_service.start_run.await_args.kwargs == {
        "workspace_id": context.workspace_id,
        "user_id": context.user_id,
    }


@pytest.mark.asyncio
async def test_task_sync_rejects_unknown_task_policy_fields_before_service_call():
    agent_id = uuid4()
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    task_service = SimpleNamespace(start_run=AsyncMock(return_value=_task(agent_id)))
    app = _app_for(task_service, context)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/v1/agents/{agent_id}/tasks/sync",
            json={
                "description": "do the work",
                "task_policy": {"unknown": {"enabled": True}},
            },
        )

    assert response.status_code == 422
    task_service.start_run.assert_not_called()


@pytest.mark.asyncio
async def test_task_sync_maps_policy_validation_error_to_422():
    agent_id = uuid4()
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    task_service = SimpleNamespace(
        start_run=AsyncMock(
            side_effect=PolicyValidationError("run_budget_usd cannot loosen higher-scope ceiling")
        )
    )
    app = _app_for(task_service, context)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/v1/agents/{agent_id}/tasks/sync",
            json={
                "description": "do the work",
                "task_policy": {"budget": {"run_budget_usd": "10.00"}},
            },
        )

    assert response.status_code == 422
    assert "run_budget_usd" in response.json()["detail"]
