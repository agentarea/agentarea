"""``runs_list`` takes at most as many runs as GET /v1/tasks does."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunsToolset


class _Tasks:
    def __init__(self):
        self.limits: list[int] = []

    async def list_page(self, *, limit, offset, agent_id):
        self.limits.append(limit)
        return []


@pytest.fixture
def tasks(monkeypatch):
    repository = _Tasks()

    @asynccontextmanager
    async def fake_context():
        factory = SimpleNamespace(create_repository=lambda _cls: repository)
        yield None, SimpleNamespace(user_id="u", workspace_id="w"), factory, None, None

    monkeypatch.setattr(runs_toolset, "platform_read_context", fake_context)
    return repository


@pytest.mark.parametrize("limit", [0, -1, 1001, 10_000_000])
async def test_a_limit_outside_the_rest_bounds_is_refused(tasks, limit):
    with pytest.raises(ToolError, match="limit"):
        await RunsToolset().list(limit=limit)
    assert tasks.limits == []


@pytest.mark.parametrize("limit", [1, 1000])
async def test_a_limit_within_the_bounds_is_read(tasks, limit):
    await RunsToolset().list(limit=limit)
    assert tasks.limits == [limit]
