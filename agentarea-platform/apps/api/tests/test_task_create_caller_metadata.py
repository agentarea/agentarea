"""Only an API caller may tell a task's tool servers who and what it runs for."""

import pytest
from agentarea_api.api.v1.agents_tasks import TASK_METADATA_MAX_BYTES, TaskCreate
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException
from pydantic import ValidationError

API_KEY_CALLER = UserContext(user_id="u", workspace_id="w", api_key_id="key-1")
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
