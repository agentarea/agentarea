"""Tests for structured task input submission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_secret_manager
from agentarea_api.api.v1 import agents_tasks
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _app_for(agent_service, workflow_service, secret_manager, context: UserContext) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")

    async def override_agent_service():
        return agent_service

    async def override_workflow_service():
        return workflow_service

    async def override_secret_manager():
        return secret_manager

    async def override_user_context():
        return context

    app.dependency_overrides[agents_tasks.get_agent_service] = override_agent_service
    app.dependency_overrides[agents_tasks.get_temporal_workflow_service] = (
        override_workflow_service
    )
    app.dependency_overrides[get_secret_manager] = override_secret_manager
    app.dependency_overrides[get_user_context] = override_user_context
    return app


@pytest.mark.asyncio
async def test_task_input_submit_stores_secrets_and_signals_refs_only():
    agent_id = uuid4()
    task_id = uuid4()
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    agent_service = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=agent_id)))
    workflow_service = SimpleNamespace(
        get_workflow_status=AsyncMock(return_value={"status": "running"}),
        send_workflow_command=AsyncMock(return_value=True),
    )
    secret_manager = SimpleNamespace(set_secret=AsyncMock())
    app = _app_for(agent_service, workflow_service, secret_manager, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{agent_id}/tasks/{task_id}/input",
            json={
                "input_request_id": "input-1",
                "answers": {"environment": "dev"},
                "secrets": {
                    "api_token": {
                        "value": "raw-secret-token",
                        "secret_name": "service/api_token",
                    }
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["secret_keys"] == ["api_token"]
    secret_manager.set_secret.assert_awaited_once_with("service/api_token", "raw-secret-token")

    workflow_service.send_workflow_command.assert_awaited_once()
    _, command, payload = workflow_service.send_workflow_command.await_args.args
    assert command == "submit_user_input"
    assert payload["answers"] == {"environment": "dev"}
    assert payload["secret_refs"] == {
        "api_token": {
            "secret_name": "service/api_token",
            "secret_ref": "secret:service/api_token",
        }
    }
    assert "raw-secret-token" not in str(payload)


@pytest.mark.asyncio
async def test_task_input_submit_rejects_completed_task():
    agent_id = uuid4()
    task_id = uuid4()
    context = UserContext(user_id="user-a", workspace_id="workspace-a")
    agent_service = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=agent_id)))
    workflow_service = SimpleNamespace(
        get_workflow_status=AsyncMock(return_value={"status": "completed"}),
        send_workflow_command=AsyncMock(return_value=True),
    )
    secret_manager = SimpleNamespace(set_secret=AsyncMock())
    app = _app_for(agent_service, workflow_service, secret_manager, context)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/agents/{agent_id}/tasks/{task_id}/input",
            json={"input_request_id": "input-1", "answers": {"environment": "dev"}},
        )

    assert response.status_code == 400
    secret_manager.set_secret.assert_not_called()
    workflow_service.send_workflow_command.assert_not_called()
