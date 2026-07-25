"""Tests for A2A push notification support.

Covers the pure config helpers, the notification body formatter, and the
JSON-RPC handlers (set/get/list/delete) with mocked task service + secret store.
See docs/adr/2026-06-20-a2a-push-notifications.md.
"""

import json
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import agents_a2a
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_common.utils import a2a_push
from agentarea_tasks.domain.models import AgentTask

# ── Pure helpers ──────────────────────────────────────────────────


def test_upsert_get_delete_push_config():
    params, stored = a2a_push.upsert_push_config({}, "https://example.com/hook")
    assert stored["url"] == "https://example.com/hook"
    assert stored["id"]
    assert a2a_push.list_push_configs(params) == [stored]

    got = a2a_push.get_push_config(params, stored["id"])
    assert got == stored

    # upsert by same id replaces, doesn't duplicate
    params2, stored2 = a2a_push.upsert_push_config(params, "https://new.example/h", stored["id"])
    assert len(a2a_push.list_push_configs(params2)) == 1
    assert a2a_push.get_push_config(params2, stored["id"])["url"] == "https://new.example/h"

    params3, removed = a2a_push.delete_push_config(params2, stored["id"])
    assert removed is True
    assert a2a_push.list_push_configs(params3) == []


def test_token_never_stored_in_params():
    params, stored = a2a_push.upsert_push_config({}, "https://example.com/hook")
    # Stored config holds only non-secret fields.
    assert "token" not in stored
    assert set(stored.keys()) == {"id", "url"}


def test_task_push_config_result_is_flat():
    result = a2a_push.task_push_config_result("task-1", {"id": "cfg-1", "url": "https://e/h"})
    # v1.0.0 flat shape: no nested pushNotificationConfig.
    assert result == {"taskId": "task-1", "id": "cfg-1", "url": "https://e/h"}


def test_push_token_secret_name():
    assert a2a_push.push_token_secret_name("t1", "c1") == "a2a_push_token:t1:c1"


def test_build_notification_body_terminal_completed():
    event = {
        "event_type": "task.completed",
        "event_id": "e1",
        "task_id": "task-1",
        "data": {"task_id": "task-1", "result": "Final answer"},
    }
    body = json.loads(a2a_push.build_push_notification_body(event))
    # v1.0.0 StreamResponse statusUpdate wrapper (no kind/final).
    su = body["statusUpdate"]
    assert su["taskId"] == "task-1"
    assert su["status"]["state"] == "COMPLETED"
    assert su["status"]["message"]["role"] == "AGENT"
    assert su["status"]["message"]["parts"][0]["text"] == "Final answer"
    assert "kind" not in su["status"]["message"]["parts"][0]


def test_build_notification_body_terminal_completed_canonical():
    # Emit-side now sends canonical dotted names; the body builder must map them.
    event = {
        "event_type": "task.completed",
        "event_id": "e1",
        "task_id": "task-1",
        "data": {"task_id": "task-1", "result": "Final answer"},
    }
    body = json.loads(a2a_push.build_push_notification_body(event))
    assert body["statusUpdate"]["status"]["state"] == "COMPLETED"


def test_build_notification_body_skips_non_terminal():
    event = {"event_type": "LLMCallChunk", "data": {"task_id": "t", "chunk": "x"}}
    assert a2a_push.build_push_notification_body(event) is None


def test_webhook_adapter_formats_terminal_only():
    from agentarea_triggers.channels.adapters import _a2a_webhook_format

    terminal = {
        "event_type": "task.completed",
        "data": {"task_id": "t", "result": "done"},
    }
    assert (
        json.loads(_a2a_webhook_format(terminal, "silent"))["statusUpdate"]["status"]["state"]
        == "COMPLETED"
    )
    # non-terminal renders empty (won't be delivered)
    assert _a2a_webhook_format({"event_type": "LLMCallChunk", "data": {}}, "silent") == ""


# ── RPC handlers ──────────────────────────────────────────────────


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

    async def get_task(self, task_id):
        return self._task


class _MockSecretManager:
    def __init__(self):
        self.secrets = {}

    async def set_secret(self, name, value):
        self.secrets[name] = value

    async def get_secret(self, name):
        return self.secrets.get(name)


def _auth():
    return A2AAuthContext(
        authenticated=True, user_id="user-1", workspace_id="ws-1", metadata={}
    )


def _task():
    return AgentTask(
        id=uuid4(),
        title="t",
        description="d",
        query="q",
        user_id="user-1",
        workspace_id="ws-1",
        agent_id=uuid4(),
        status="working",
        task_parameters={},
        metadata={},
    )


@pytest.mark.asyncio
async def test_push_config_set_stores_token_in_secret_store(monkeypatch):
    monkeypatch.setattr(agents_a2a, "validate_outbound_url", lambda url: None)
    task = _task()
    svc = _MockTaskService(task)
    secrets = _MockSecretManager()

    params = {
        "taskId": str(task.id),
        "url": "https://example.com/hook",
        "token": "secret-tok",
    }
    resp = await agents_a2a.handle_push_config_set(
        "rpc-1", params, svc, task.agent_id, _auth(), secrets
    )
    result = resp.result
    # v1.0.0 flat result shape.
    assert result["taskId"] == str(task.id)
    assert result["url"] == "https://example.com/hook"
    # Token NOT echoed back.
    assert "token" not in result
    # Token went to the secret store under the canonical key.
    cfg_id = result["id"]
    assert secrets.secrets[f"a2a_push_token:{task.id}:{cfg_id}"] == "secret-tok"
    # Non-secret config persisted to task_parameters.
    _, task_update = svc.task_repository.updated
    assert task_update.task_parameters["a2a_push_configs"][0]["url"] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_push_config_set_rejects_unsafe_url(monkeypatch):
    from agentarea_common.utils.url_safety import UnsafeUrlError

    def _raise(url):
        raise UnsafeUrlError("private address")

    monkeypatch.setattr(agents_a2a, "validate_outbound_url", _raise)
    task = _task()
    resp = await agents_a2a.handle_push_config_set(
        "rpc-2",
        {"taskId": str(task.id), "url": "http://169.254.169.254/"},
        _MockTaskService(task),
        task.agent_id,
        _auth(),
        _MockSecretManager(),
    )
    assert resp.error.code == -32602


@pytest.mark.asyncio
async def test_push_config_list_and_delete(monkeypatch):
    monkeypatch.setattr(agents_a2a, "validate_outbound_url", lambda url: None)
    task = _task()
    svc = _MockTaskService(task)
    secrets = _MockSecretManager()

    set_resp = await agents_a2a.handle_push_config_set(
        "s", {"taskId": str(task.id), "url": "https://e.com/h"},
        svc, task.agent_id, _auth(), secrets,
    )
    cfg_id = set_resp.result["id"]
    # Reflect the persisted params back onto the task for subsequent reads.
    task.task_parameters = svc.task_repository.updated[1].task_parameters

    list_resp = await agents_a2a.handle_push_config_list(
        "l", {"id": str(task.id)}, svc, task.agent_id, _auth()
    )
    assert [c["id"] for c in list_resp.result] == [cfg_id]

    del_resp = await agents_a2a.handle_push_config_delete(
        "d", {"id": str(task.id), "pushNotificationConfigId": cfg_id},
        svc, task.agent_id, _auth(), secrets,
    )
    assert del_resp.result is None
    task.task_parameters = svc.task_repository.updated[1].task_parameters
    list_resp2 = await agents_a2a.handle_push_config_list(
        "l2", {"id": str(task.id)}, svc, task.agent_id, _auth()
    )
    assert list_resp2.result == []
