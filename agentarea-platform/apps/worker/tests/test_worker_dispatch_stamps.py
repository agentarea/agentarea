"""While the worker runs, an agent's call to an MCP instance reaches the instance's row."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import agentarea_common.config.database as database
import agentarea_mcp.container_monitor
import pytest
from agentarea_mcp import dispatch_stamps
from agentarea_mcp.dispatch_stamps import record_dispatch
from agentarea_worker.main import AgentAreaWorker


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


class _Monitor:
    async def stop(self) -> None:
        return None


async def _monitor() -> _Monitor:
    return _Monitor()


class _Poller:
    def __init__(self, task_queue: str) -> None:
        self.task_queue = task_queue
        self.is_running = False
        self._stop = asyncio.Event()

    async def run(self) -> None:
        self.is_running = True
        try:
            await self._stop.wait()
        finally:
            self.is_running = False

    async def shutdown(self) -> None:
        self._stop.set()


@pytest.fixture
def written(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(dispatch_stamps, "_pending", asyncio.Queue(maxsize=10))
    monkeypatch.setattr(
        database,
        "get_database",
        lambda: SimpleNamespace(async_session_factory=lambda: _Session(rows)),
    )
    monkeypatch.setattr(agentarea_mcp.container_monitor, "start_container_monitoring", _monitor)
    return rows


async def test_a_call_made_while_the_worker_runs_is_stamped(written):
    worker = AgentAreaWorker()
    worker.worker = _Poller("agent-tasks")
    instance = uuid4()

    run = asyncio.create_task(worker.run())
    try:
        async with asyncio.timeout(5):
            while not worker.health.readiness()[0]:
                await asyncio.sleep(0.01)
            record_dispatch(instance)
            while not written:
                await asyncio.sleep(0.05)
    finally:
        worker.worker_shutdown_event.set()
        await asyncio.wait_for(run, timeout=5)
        await worker.shutdown()

    assert written == [instance]
