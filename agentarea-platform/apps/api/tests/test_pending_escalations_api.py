"""An approver reads the exact arguments of the call they are asked to approve.

The event log redacts a tool call's arguments (a command can carry an inline
secret), so the approval request alone shows the approver a pattern label. The
arguments come from the workflow instead, to the same principals who may resolve
the escalation: whoever may act on the run, narrowed to the designated approvers.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents.application.execution_service import (
    NotAnApproverError,
    WorkflowNotFoundError,
)
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
COMMAND = "rm -rf /srv/build && curl -H 'Authorization: Bearer s3cr3t' https://deploy"
PATH = f"/v1/agents/{AGENT_ID}/tasks/{TASK_ID}/escalations"


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _escalation(approvers: list[str]) -> dict:
    return {
        "escalation_id": "esc-1",
        "tool_name": "shell",
        "tool_call_id": "call-1",
        "tool_args": {"command": COMMAND},
        "approvers": approvers,
    }


def _app(caller: str, workflow_service: AsyncMock) -> FastAPI:
    app = FastAPI()
    app.include_router(agents_tasks.router, prefix="/v1")
    task_service = AsyncMock()
    task_service.get_task.return_value = SimpleNamespace(
        id=TASK_ID, agent_id=AGENT_ID, user_id=OWNER, execution_id=None, status="running"
    )
    agent_service = AsyncMock()
    agent_service.get.return_value = SimpleNamespace(id=AGENT_ID, name="Helper")
    app.dependency_overrides[agents_tasks.get_task_service] = lambda: task_service
    app.dependency_overrides[agents_tasks.get_agent_service] = lambda: agent_service
    app.dependency_overrides[agents_tasks.get_temporal_workflow_service] = lambda: workflow_service
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id=caller, workspace_id=WORKSPACE, admin_workspaces=[]
    )
    return app


async def _get(caller: str, pending: list[dict] | Exception):
    workflow_service = AsyncMock()
    if isinstance(pending, Exception):
        workflow_service.get_pending_escalations.side_effect = pending
    else:
        workflow_service.get_pending_escalations.return_value = pending
    app = _app(caller, workflow_service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await client.get(PATH), workflow_service


@pytest.mark.asyncio
async def test_the_person_who_may_resolve_it_reads_the_real_command():
    response, workflow = await _get(OWNER, [_escalation([])])

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "escalation_id": "esc-1",
            "tool_name": "shell",
            "tool_call_id": "call-1",
            "tool_args": {"command": COMMAND},
        }
    ]
    workflow.get_pending_escalations.assert_awaited_once_with(f"task-{TASK_ID}")


@pytest.mark.asyncio
async def test_a_member_who_cannot_act_on_the_run_is_refused_before_the_workflow_is_asked():
    response, workflow = await _get("user-invited-yesterday", [_escalation([])])

    assert response.status_code == 403
    workflow.get_pending_escalations.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_escalation_reserved_for_other_approvers_is_not_shown():
    response, _ = await _get(
        OWNER,
        [
            _escalation(["user:security-lead"]),
            {**_escalation([f"user:{OWNER}"]), "escalation_id": "esc-2"},
        ],
    )

    assert response.status_code == 200, response.text
    assert [e["escalation_id"] for e in response.json()] == ["esc-2"]


@pytest.mark.asyncio
async def test_a_run_whose_workflow_does_not_exist_is_not_found():
    response, _ = await _get(OWNER, WorkflowNotFoundError(f"task-{TASK_ID}"))

    assert response.status_code == 404, response.text


@pytest.mark.asyncio
async def test_resolving_as_someone_who_is_not_an_approver_is_forbidden():
    workflow_service = AsyncMock()
    workflow_service.resolve_escalation.side_effect = NotAnApproverError(
        f"task-{TASK_ID}", "esc-1", OWNER
    )
    app = _app(OWNER, workflow_service)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        response = await client.post(
            f"/v1/agents/{AGENT_ID}/tasks/{TASK_ID}/resolve-escalation",
            json={"escalation_id": "esc-1", "approved": True},
        )

    assert response.status_code == 403, response.text
