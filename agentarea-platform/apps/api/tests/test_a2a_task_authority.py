"""A2A JSON-RPC does not bypass run authority.

``CancelTask`` and the push-notification config methods (create/get/list/
delete) act on an existing task by id. REST (``requires_task_authority``)
and the MCP runs toolset (``_refuse_unless_may_act``) already require the
caller to have started the run, or to administer the workspace, before
acting on it. Without the same check here, any workspace member could
cancel another member's run, or register a webhook that receives that
task's events and result, by task id alone.

Driven through the real ``/a2a/rpc`` route, so the refusal is asserted the
way a caller sees it: an HTTP 403, not a JSON-RPC error body.
"""

from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from agentarea_api.api.deps.services import get_agent_service, get_secret_manager, get_task_service
from agentarea_api.api.v1 import a2a_request_handler, agents_a2a
from agentarea_common.auth import access
from agentarea_common.auth.access import EdgeDecision
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_optional_user
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.events.contract import TASK_COMPLETED
from agentarea_common.events.task_stream import TaskEventEnvelope
from agentarea_common.utils.a2a_push import upsert_push_config
from agentarea_tasks.domain.models import AgentTask
from fastapi import FastAPI, Request

WORKSPACE = "ws-acme"
OWNER = "user-who-started-it"
OTHER_MEMBER = "user-invited-yesterday"
ADMIN = "user-workspace-admin"
AGENT_ID = uuid4()
TASK_ID = uuid4()
RPC = f"http://t/v1/agents/{AGENT_ID}/a2a/rpc"

AGENT = SimpleNamespace(
    id=AGENT_ID,
    name="helper",
    description=None,
    status="active",
    workspace_id=WORKSPACE,
    tools=None,
    planning=None,
    a2ui_enabled=False,
)


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


@pytest.fixture(autouse=True)
def _resolve_admin(monkeypatch):
    """A2A mints its own ``UserContext`` outside the HTTP boundary, so
    ``admin_workspaces`` is resolved lazily the same way the MCP bearer path
    does -- see ``_ensure_admin_workspaces_resolved``.
    """

    async def fake_administered_workspace_ids(user_id):
        return [WORKSPACE] if user_id == ADMIN else []

    monkeypatch.setattr(
        "agentarea_common.workspaces.authority.administered_workspace_ids",
        fake_administered_workspace_ids,
    )


class _TaskRepo:
    def __init__(self):
        self.updated = None

    async def update_by_id(self, task_id, task_update):
        self.updated = (task_id, task_update)


class _TaskService:
    def __init__(self, task):
        self._task = task
        self.task_repository = _TaskRepo()
        self.cancelled = False

    async def get_task(self, task_id):
        return self._task if task_id == self._task.id else None

    async def get_task_with_workflow_status(self, task_id):
        return await self.get_task(task_id)

    async def cancel_task(self, task_id):
        self.cancelled = True
        return True


class _SecretManager:
    async def set_secret(self, name, value):
        pass

    async def delete_secret(self, name):
        return True


class _AgentService:
    async def get(self, agent_id):
        return AGENT


def _task():
    task_parameters, _ = upsert_push_config({}, "https://existing.example/hook", "cfg-1")
    return AgentTask(
        id=TASK_ID,
        title="t",
        description="d",
        query="q",
        user_id=OWNER,
        workspace_id=WORKSPACE,
        agent_id=AGENT_ID,
        status="working",
        task_parameters=task_parameters,
        metadata={},
    )


def _subject(request: Request) -> UserContext:
    return UserContext(user_id=request.headers["x-test-user"], workspace_id=WORKSPACE)


async def _allow(subject, action, *, agent_workspace_id, agent_id):
    return EdgeDecision(allowed=True, reason="workspace member")


@pytest.fixture
def svc(monkeypatch):
    async def feed(task_id, **kwargs):
        yield TaskEventEnvelope(
            event_type=TASK_COMPLETED, event_id="1", timestamp=None, data={"result": "done"}
        )

    monkeypatch.setattr(access, "authorize_agent_action", _allow)
    monkeypatch.setattr(agents_a2a, "open_task_event_feed", feed)
    monkeypatch.setattr(a2a_request_handler, "validate_outbound_url", lambda url: None)
    return _TaskService(_task())


@pytest.fixture
def call(svc):
    app = FastAPI()
    app.include_router(agents_a2a.router, prefix="/v1/agents/{agent_id}")
    app.dependency_overrides[get_optional_user] = _subject
    app.dependency_overrides[get_task_service] = lambda: svc
    app.dependency_overrides[get_agent_service] = _AgentService
    app.dependency_overrides[get_secret_manager] = _SecretManager

    async def _call(user: str, method: str, params: dict) -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            return await client.post(
                RPC,
                json={"jsonrpc": "2.0", "id": "r", "method": method, "params": params},
                headers={"A2A-Version": "1.0", "x-test-user": user},
            )

    return _call


TASK = str(TASK_ID)
METHODS = {
    "CancelTask": {"id": TASK},
    "CreateTaskPushNotificationConfig": {"taskId": TASK, "url": "https://example.com/hook"},
    "GetTaskPushNotificationConfig": {"taskId": TASK, "id": "cfg-1"},
    "ListTaskPushNotificationConfigs": {"taskId": TASK},
    "DeleteTaskPushNotificationConfig": {"taskId": TASK, "id": "cfg-1"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
async def test_a_member_who_did_not_start_the_run_is_refused(call, method):
    response = await call(OTHER_MEMBER, method, METHODS[method])

    assert response.status_code == 403
    assert "error" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
async def test_the_member_who_started_the_run_is_not_refused(call, method):
    response = await call(OWNER, method, METHODS[method])

    assert response.status_code == 200
    assert "error" not in response.json(), response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
async def test_a_workspace_admin_is_not_refused(call, method):
    response = await call(ADMIN, method, METHODS[method])

    assert response.status_code == 200
    assert "error" not in response.json(), response.json()


@pytest.mark.asyncio
async def test_refusal_happens_before_any_mutation(call, svc):
    assert (await call(OTHER_MEMBER, "CancelTask", METHODS["CancelTask"])).status_code == 403
    assert svc.cancelled is False

    create = "CreateTaskPushNotificationConfig"
    assert (await call(OTHER_MEMBER, create, METHODS[create])).status_code == 403
    assert svc.task_repository.updated is None


@pytest.mark.asyncio
async def test_reading_a_run_stays_a_workspace_level_read(call):
    got = await call(OTHER_MEMBER, "GetTask", {"id": TASK})
    assert got.status_code == 200
    assert got.json()["result"]["id"] == TASK

    stream = await call(OTHER_MEMBER, "SubscribeToTask", {"id": TASK})
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert '"task"' in stream.text
    assert "TASK_STATE_COMPLETED" in stream.text
