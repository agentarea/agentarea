"""A Temporal worker that stops polling must take the worker process down with it."""

import asyncio

import agentarea_mcp.container_monitor
import pytest
from agentarea_worker.main import AgentAreaWorker


class _Monitor:
    async def stop(self) -> None:
        return None


async def _monitor() -> _Monitor:
    return _Monitor()


class _Poller:
    def __init__(self, task_queue: str, error: Exception | None = None) -> None:
        self.task_queue = task_queue
        self.is_running = False
        self._error = error

    async def run(self) -> None:
        self.is_running = True
        try:
            await asyncio.sleep(0)
            if self._error:
                raise self._error
            await asyncio.Event().wait()
        finally:
            self.is_running = False


@pytest.fixture
def worker(monkeypatch) -> AgentAreaWorker:
    monkeypatch.setattr(agentarea_mcp.container_monitor, "start_container_monitoring", _monitor)
    return AgentAreaWorker()


async def test_run_raises_when_a_temporal_worker_stops_polling(worker):
    worker.worker = _Poller("agent-tasks", error=RuntimeError("namespace not found"))
    worker.trigger_worker = _Poller("trigger-schedules")

    with pytest.raises(RuntimeError, match="agent-tasks stopped polling") as raised:
        await asyncio.wait_for(worker.run(), timeout=5)

    assert str(raised.value.__cause__) == "namespace not found"
    assert worker.trigger_worker.is_running is False


async def test_run_returns_on_shutdown_signal(worker):
    worker.worker = _Poller("agent-tasks")
    worker.trigger_worker = _Poller("trigger-schedules")

    run = asyncio.create_task(worker.run())
    for _ in range(100):
        if worker.health.readiness()[0]:
            break
        await asyncio.sleep(0.01)
    assert worker.health.readiness() == (True, "ready")

    worker.worker_shutdown_event.set()
    await asyncio.wait_for(run, timeout=5)
    assert worker.health.readiness()[0] is False
