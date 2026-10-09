"""While the API runs, a call it makes to an MCP instance reaches the instance's row.

The API calls MCP tools itself (client endpoints, ``tools_call``), and a call only
queues its stamp; nothing wrote the queue, so every instance read "never called".
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import agentarea_api.api.events.events_router as events_router
import agentarea_api.main as api_main
import agentarea_common.config.database as database
import agentarea_common.observability.metrics as metrics
import pytest
from agentarea_mcp import dispatch_stamps
from agentarea_mcp.dispatch_stamps import record_dispatch


class _Session:
    def __init__(self, written: list) -> None:
        self._written = written

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, statement):
        self._written.append(statement.compile().params["id_1"])

    async def commit(self):
        return None


@pytest.fixture
def written(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(dispatch_stamps, "_pending", asyncio.Queue(maxsize=10))
    monkeypatch.setattr(
        database,
        "get_database",
        lambda: SimpleNamespace(async_session_factory=lambda: _Session(rows)),
    )
    monkeypatch.setattr(
        api_main, "initialize_services", AsyncMock(return_value=SimpleNamespace(aclose=AsyncMock()))
    )
    monkeypatch.setattr(api_main, "cleanup_all_connections", AsyncMock())
    monkeypatch.setattr(events_router, "start_events_router", AsyncMock())
    monkeypatch.setattr(events_router, "stop_events_router", AsyncMock())
    monkeypatch.setattr(metrics, "start_metrics_server", lambda port: MagicMock())
    return rows


async def test_a_call_made_while_the_api_runs_is_stamped(written):
    instance = uuid4()

    async with api_main.app_lifespan(MagicMock()):
        record_dispatch(instance)
        async with asyncio.timeout(5):
            while not written:
                await asyncio.sleep(0.05)

    assert written == [instance]


async def test_a_call_made_just_before_shutdown_is_still_stamped(written):
    instance = uuid4()

    async with api_main.app_lifespan(MagicMock()):
        record_dispatch(instance)

    assert written == [instance]
