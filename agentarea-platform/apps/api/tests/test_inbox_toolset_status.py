"""The inbox tool reads the same status vocabulary as GET /v1/inbox.

It kept its own copy and widened an unknown status to "every inbox status", so
an agent asking for `status="running"` got the whole inbox back as if that were
the answer. The router rejects an unknown status with 422; the tool must refuse
it too.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import inbox as inbox_router
from agentarea_api.tools import inbox_toolset
from agentarea_api.tools.inbox_toolset import InboxToolset
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.statuses import INBOX_STATUSES


@pytest.fixture(autouse=True)
def caller():
    with use_mcp_user_context(UserContext(user_id="user-1", workspace_id="ws-1")):
        yield


@pytest.fixture
def repository(monkeypatch):
    repository = SimpleNamespace(
        list_by_statuses=AsyncMock(return_value=[]),
        count_by_statuses=AsyncMock(return_value=0),
    )
    opened = []

    @asynccontextmanager
    async def fake_context():
        opened.append(True)
        yield (None, None, None, None, None)

    monkeypatch.setattr(inbox_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(
        "agentarea_api.api.deps.services._create_task_manager", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "agentarea_api.api.deps.services.get_temporal_workflow_service",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "agentarea_tasks.task_service.TaskService",
        lambda **_: SimpleNamespace(task_repository=repository),
    )
    repository.opened = opened
    return repository


def test_the_router_and_the_tool_share_one_vocabulary() -> None:
    assert inbox_router.INBOX_STATUSES is INBOX_STATUSES
    assert inbox_toolset.INBOX_STATUSES is INBOX_STATUSES


@pytest.mark.asyncio
async def test_an_unknown_status_is_refused(repository) -> None:
    result = json.loads(await InboxToolset().list(status="running"))

    assert "running" in result["error"]
    assert not repository.opened
    repository.list_by_statuses.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_known_status_narrows_the_query(repository) -> None:
    await InboxToolset().list(status="waiting_for_input")

    assert repository.list_by_statuses.await_args.kwargs["statuses"] == ["waiting_for_input"]


@pytest.mark.asyncio
async def test_no_status_asks_for_the_whole_vocabulary(repository) -> None:
    await InboxToolset().list()

    assert repository.list_by_statuses.await_args.kwargs["statuses"] == list(INBOX_STATUSES)
