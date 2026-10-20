"""Only an API caller may tell a task's tool servers who and what it runs for."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import TASK_METADATA_MAX_BYTES, TaskCreate, TaskResponse
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.credential import Credential
from fastapi import HTTPException
from pydantic import ValidationError

API_KEY_CALLER = UserContext(
    user_id="u", workspace_id="w", credential=Credential(kind="api_key", key_id="key-1")
)
SESSION_CALLER = UserContext(user_id="u", workspace_id="w")


def test_an_api_key_caller_sets_end_user_and_metadata():
    task = TaskCreate(description="d", metadata={"chatId": "c-1"}, end_user_id="eu-1")

    assert task.trusted_metadata(API_KEY_CALLER) == {
        "app_metadata": {"chatId": "c-1"},
        "end_user_id": "eu-1",
    }


def test_a_session_caller_cannot_assert_them():
    task = TaskCreate(description="d", end_user_id="someone-else")

    with pytest.raises(HTTPException) as refused:
        task.trusted_metadata(SESSION_CALLER)
    assert refused.value.status_code == 403


def test_a_task_without_them_is_unchanged_for_any_caller():
    assert TaskCreate(description="d").trusted_metadata(SESSION_CALLER) == {}


def test_metadata_is_size_limited():
    with pytest.raises(ValidationError, match="bytes of JSON"):
        TaskCreate(description="d", metadata={"blob": "x" * TASK_METADATA_MAX_BYTES})


def test_an_api_key_caller_registers_a_webhook_without_its_secret_in_metadata():
    task = TaskCreate(
        description="d",
        webhook={"url": "https://8.8.8.8/hook", "secret": "s" * 32},
    )

    trusted = task.trusted_metadata(API_KEY_CALLER)

    assert trusted == {"task_webhook": {"url": "https://8.8.8.8/hook", "signed": True}}
    assert "s" * 32 not in str(trusted)


def test_a_session_caller_cannot_register_a_webhook():
    task = TaskCreate(description="d", webhook={"url": "https://8.8.8.8/hook"})

    with pytest.raises(HTTPException) as refused:
        task.trusted_metadata(SESSION_CALLER)
    assert refused.value.status_code == 403


def test_a_webhook_url_that_is_not_http_is_refused():
    task = TaskCreate(description="d", webhook={"url": "file:///etc/passwd"})

    with pytest.raises(HTTPException) as refused:
        task.trusted_metadata(API_KEY_CALLER)
    assert refused.value.status_code == 422


def _stored_task(**overrides):
    fields = {
        "id": uuid4(),
        "agent_id": uuid4(),
        "description": "d",
        "task_parameters": {},
        "status": "completed",
        "result": {"response": "ok", "total_cost": "0.0125", "tokens_used": 1500},
        "error_message": None,
        "created_at": "2026-10-12T10:00:00Z",
        "execution_id": "e",
        "scheduled_at": None,
        "user_id": "u",
        "provenance": {},
        "metadata": {"end_user_id": "eu-1", "app_metadata": {"chatId": "c-1"}},
    }
    return SimpleNamespace(**{**fields, **overrides})


def test_an_api_key_caller_reads_back_end_user_metadata_cost_and_tokens():
    read = TaskResponse.from_agent_task(_stored_task(), API_KEY_CALLER)

    assert (read.end_user_id, read.metadata) == ("eu-1", {"chatId": "c-1"})
    assert (read.total_cost, read.total_tokens) == (0.0125, 1500)


def test_a_session_caller_reads_cost_but_not_the_callers_context():
    read = TaskResponse.from_agent_task(_stored_task(), SESSION_CALLER)

    assert (read.end_user_id, read.metadata) == (None, None)
    assert read.total_tokens == 1500
