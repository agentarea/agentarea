"""``runs_get_events`` shows a tool call to each caller as REST does."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunEventsPage, RunsToolset

from .tool_call_log import BEARER, PASSWORD, FakeFeedReader, assert_owner_view


@pytest.mark.parametrize("may_act", [True, False])
async def test_the_tasks_authority_sees_the_command_and_output_and_a_member_does_not(
    monkeypatch, may_act
):
    task = SimpleNamespace(id=uuid4(), user_id="starter")
    tasks = SimpleNamespace(get_task=AsyncMock(return_value=task))
    caller = SimpleNamespace(user_id="caller", workspace_id="w")

    @asynccontextmanager
    async def fake_context():
        factory = SimpleNamespace(
            session=None, user_context=caller, create_repository=lambda _cls: tasks
        )
        yield None, caller, factory, None, None

    decide = AsyncMock(return_value=may_act)
    monkeypatch.setattr(runs_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(runs_toolset, "TaskFeedReader", FakeFeedReader)
    monkeypatch.setattr(runs_toolset, "caller_may_act_on_task", decide)

    body = json.loads(await RunsToolset().get_events(str(task.id)))

    RunEventsPage.model_validate(body)
    call, result = body["events"]
    decide.assert_awaited_once_with(task, caller)
    if may_act:
        assert_owner_view(call, result)
    else:
        text = json.dumps(body)
        assert BEARER not in text and PASSWORD not in text and "items: 3" not in text
        assert call["argument_names"] == ["command", "password"]
        assert "arguments" not in call and "result" not in result
