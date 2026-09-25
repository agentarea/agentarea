"""Tests for A2A push notification support.

Covers the pure config helpers, the notification body formatter, and the
JSON-RPC handlers (set/get/list/delete) with mocked task service + secret store.
See docs/adr/2026-06-20-a2a-push-notifications.md.
"""

import json
from uuid import uuid4

import pytest
from a2a.types import StreamResponse, TaskPushNotificationConfig
from a2a.utils.errors import InvalidParamsError
from agentarea_api.api.v1 import a2a_request_handler
from agentarea_api.api.v1.a2a_auth import A2AAuthContext
from agentarea_api.api.v1.a2a_request_handler import (
    A2A_SCOPE_KEY,
    A2ACallScope,
    AgentAreaRequestHandler,
)
from agentarea_common.utils import a2a_push
from agentarea_tasks.domain.models import AgentTask
from google.protobuf.json_format import Parse

# ── Pure helpers ──────────────────────────────────────────────────


def test_upsert_get_delete_push_config():
    params, stored = a2a_push.upsert_push_config({}, "https://example.com/hook")
    assert stored["url"] == "https://example.com/hook"
    assert stored["id"]
    assert a2a_push.list_push_configs(params) == [stored]

    got = a2a_push.get_push_config(params, stored["id"])
    assert got == stored

    # upsert by same id replaces, doesn't duplicate
    params2, _ = a2a_push.upsert_push_config(params, "https://new.example/h", stored["id"])
    assert len(a2a_push.list_push_configs(params2)) == 1
    assert a2a_push.get_push_config(params2, stored["id"])["url"] == "https://new.example/h"

    params3, removed = a2a_push.delete_push_config(params2, stored["id"])
    assert removed is True
    assert a2a_push.list_push_configs(params3) == []


def test_token_never_stored_in_params():
    _, stored = a2a_push.upsert_push_config({}, "https://example.com/hook")
    # Stored config holds only non-secret fields.
    assert "token" not in stored
    assert set(stored.keys()) == {"id", "url"}


def test_task_push_config_result_omits_the_token():
    result = a2a_push.task_push_config_result("task-1", {"id": "cfg-1", "url": "https://e/h"})
    assert result == TaskPushNotificationConfig(task_id="task-1", id="cfg-1", url="https://e/h")


def test_push_token_secret_name():
    assert a2a_push.push_token_secret_name("t1", "c1") == "a2a_push_token:t1:c1"


def test_build_notification_body_terminal_completed():
    event = {
        "event_type": "task.completed",
        "event_id": "e1",
        "task_id": "task-1",
        "data": {"task_id": "task-1", "result": "Final answer"},
    }
    raw = a2a_push.build_push_notification_body(event)
    # A StreamResponse carrying a statusUpdate, parseable by any A2A v1 client.
    Parse(raw, StreamResponse())
    su = json.loads(raw)["statusUpdate"]
    assert su["taskId"] == "task-1"
    assert su["status"]["state"] == "TASK_STATE_COMPLETED"
    assert su["status"]["message"]["role"] == "ROLE_AGENT"
    assert su["status"]["message"]["parts"][0]["text"] == "Final answer"


def test_build_notification_body_terminal_completed_canonical():
    # Emit-side now sends canonical dotted names; the body builder must map them.
    event = {
        "event_type": "task.completed",
        "event_id": "e1",
        "task_id": "task-1",
        "data": {"task_id": "task-1", "result": "Final answer"},
    }
    body = json.loads(a2a_push.build_push_notification_body(event))
    assert body["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"


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
        == "TASK_STATE_COMPLETED"
    )
    # non-terminal renders empty (won't be delivered)
    assert _a2a_webhook_format({"event_type": "LLMCallChunk", "data": {}}, "silent") == ""


# ── Request handler ───────────────────────────────────────────────


class _MockTaskRepo:
    def __init__(self):
        self.updated = None

    async def update_by_id(self, task_id, task_update):
        self.updated = (task_id, task_update)


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


def _handler(task):
    return AgentAreaRequestHandler(
        task_service=_MockTaskService(task),
        agent_service=None,
        secret_manager=_MockSecretManager(),
        event_feed=None,
    )


def _context(task):
    from a2a.server.context import ServerCallContext

    auth = A2AAuthContext(authenticated=True, user_id="user-1", workspace_id="ws-1")
    return ServerCallContext(
        state={
            A2A_SCOPE_KEY: A2ACallScope(agent_id=task.agent_id, auth=auth, base_url="http://t"),
            "method": "CreateTaskPushNotificationConfig",
        }
    )


@pytest.mark.asyncio
async def test_push_config_create_stores_token_in_secret_store(monkeypatch):
    monkeypatch.setattr(a2a_request_handler, "validate_outbound_url", lambda url: None)
    task = _task()
    handler = _handler(task)

    result = await handler.on_create_task_push_notification_config(
        TaskPushNotificationConfig(
            task_id=str(task.id),
            url="https://example.com/hook",
            token="secret-tok",  # noqa: S106 -- a fixture value, not a credential
        ),
        _context(task),
    )

    assert (result.task_id, result.url, result.token) == (
        str(task.id),
        "https://example.com/hook",
        "",
    )
    assert handler._secrets.secrets[f"a2a_push_token:{task.id}:{result.id}"] == "secret-tok"
    _, task_update = handler._tasks.task_repository.updated
    assert task_update.task_parameters["a2a_push_configs"][0]["url"] == "https://example.com/hook"


@pytest.mark.asyncio
async def test_push_config_create_rejects_unsafe_url(monkeypatch):
    from agentarea_common.utils.url_safety import UnsafeUrlError

    def _raise(url):
        raise UnsafeUrlError("private address")

    monkeypatch.setattr(a2a_request_handler, "validate_outbound_url", _raise)
    task = _task()

    with pytest.raises(InvalidParamsError, match="Unsafe webhook url"):
        await _handler(task).on_create_task_push_notification_config(
            TaskPushNotificationConfig(task_id=str(task.id), url="http://169.254.169.254/"),
            _context(task),
        )
