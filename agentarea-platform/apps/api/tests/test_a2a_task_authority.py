"""A2A JSON-RPC does not bypass run authority.

``CancelTask`` and the push-notification config methods (create/get/list/
delete) act on an existing task by id. REST (``requires_task_authority``)
and the MCP runs toolset (``_refuse_unless_may_act``) already require the
caller to have started the run, or to administer the workspace, before
acting on it. Without the same check here, any workspace member could
cancel another member's run, or register a webhook that receives that
task's events and result, by task id alone.
"""

from uuid import uuid4

import pytest
from agentarea_api.api.v1 import agents_a2a
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.utils.a2a_push import upsert_push_config
from agentarea_tasks.domain.models import AgentTask
from fastapi import HTTPException

WORKSPACE = "ws-acme"
OWNER = "user-who-started-it"
OTHER_MEMBER = "user-invited-yesterday"
ADMIN = "user-workspace-admin"
AGENT_ID = uuid4()
TASK_ID = uuid4()


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


class _MockTaskRepo:
    def __init__(self):
        self.updated = None

    async def update_by_id(self, task_id, task_update):
        self.updated = (task_id, task_update)
        return None


class _MockTaskService:
    def __init__(self, task):
        self._task = task
        self.task_repository = _MockTaskRepo()
        self.cancelled = False

    async def get_task(self, task_id):
        return self._task

    async def get_task_with_workflow_status(self, task_id):
        return self._task

    async def cancel_task(self, task_id):
        self.cancelled = True
        return True


class _MockSecretManager:
    def __init__(self):
        self.secrets = {}

    async def set_secret(self, name, value):
        self.secrets[name] = value


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


def _auth(user_id):
    return A2AAuthContext(authenticated=True, user_id=user_id, workspace_id=WORKSPACE, metadata={})


def _cancel(svc, auth):
    return agents_a2a.handle_task_cancel("r", {"id": str(TASK_ID)}, svc, AGENT_ID, auth)


def _push_set(svc, auth):
    return agents_a2a.handle_push_config_set(
        "r",
        {"taskId": str(TASK_ID), "url": "https://example.com/hook"},
        svc,
        AGENT_ID,
        auth,
        _MockSecretManager(),
    )


def _push_get(svc, auth):
    return agents_a2a.handle_push_config_get("r", {"id": str(TASK_ID)}, svc, AGENT_ID, auth)


def _push_list(svc, auth):
    return agents_a2a.handle_push_config_list("r", {"id": str(TASK_ID)}, svc, AGENT_ID, auth)


def _push_delete(svc, auth):
    return agents_a2a.handle_push_config_delete(
        "r",
        {"id": str(TASK_ID), "pushNotificationConfigId": "cfg-1"},
        svc,
        AGENT_ID,
        auth,
        _MockSecretManager(),
    )


METHODS = {
    "cancel": _cancel,
    "push_config_set": _push_set,
    "push_config_get": _push_get,
    "push_config_list": _push_list,
    "push_config_delete": _push_delete,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
async def test_a_member_who_did_not_start_the_run_is_refused(monkeypatch, method):
    monkeypatch.setattr(agents_a2a, "validate_outbound_url", lambda url: None)
    svc = _MockTaskService(_task())

    with pytest.raises(HTTPException) as exc_info:
        await METHODS[method](svc, _auth(OTHER_MEMBER))

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
async def test_the_member_who_started_the_run_is_not_refused(monkeypatch, method):
    monkeypatch.setattr(agents_a2a, "validate_outbound_url", lambda url: None)
    svc = _MockTaskService(_task())

    resp = await METHODS[method](svc, _auth(OWNER))

    assert resp.error is None, resp.error


@pytest.mark.asyncio
@pytest.mark.parametrize("method", METHODS)
async def test_a_workspace_admin_is_not_refused(monkeypatch, method):
    monkeypatch.setattr(agents_a2a, "validate_outbound_url", lambda url: None)
    svc = _MockTaskService(_task())

    resp = await METHODS[method](svc, _auth(ADMIN))

    assert resp.error is None, resp.error


@pytest.mark.asyncio
async def test_refusal_happens_before_any_mutation(monkeypatch):
    monkeypatch.setattr(agents_a2a, "validate_outbound_url", lambda url: None)
    svc = _MockTaskService(_task())

    with pytest.raises(HTTPException):
        await _cancel(svc, _auth(OTHER_MEMBER))
    assert svc.cancelled is False

    with pytest.raises(HTTPException):
        await _push_set(svc, _auth(OTHER_MEMBER))
    assert svc.task_repository.updated is None
