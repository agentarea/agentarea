"""Worker health: readiness must mean "polling Temporal", liveness "loop answers"."""

import asyncio
import uuid

import pytest
from agentarea_common.testing.temporal import temporal_download_dir
from agentarea_worker.health import (
    HealthServer,
    WorkerHealth,
    WorkerHealthSettings,
    respond,
)
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker


class _Poller:
    def __init__(self, is_running: bool) -> None:
        self.is_running = is_running


def test_not_ready_before_startup_completes():
    ready, reason = WorkerHealth().readiness()

    assert ready is False
    assert reason == "starting"


def test_ready_once_started_and_every_poller_runs():
    health = WorkerHealth()
    health.mark_started({"agent-tasks": _Poller(True), "trigger-schedules": _Poller(True)})

    assert health.readiness() == (True, "ready")


def test_not_ready_while_a_poller_is_not_running():
    health = WorkerHealth()
    health.mark_started({"agent-tasks": _Poller(True), "trigger-schedules": _Poller(False)})

    ready, reason = health.readiness()

    assert ready is False
    assert "trigger-schedules" in reason
    assert "agent-tasks" not in reason


def test_mark_started_requires_pollers():
    with pytest.raises(ValueError):
        WorkerHealth().mark_started({})


def test_liveness_does_not_depend_on_readiness():
    assert respond(WorkerHealth(), "GET", "/livez")[0] == 200


def test_readyz_is_503_until_ready_then_200():
    health = WorkerHealth()
    assert respond(health, "GET", "/readyz")[0] == 503

    health.mark_started({"agent-tasks": _Poller(True)})
    assert respond(health, "GET", "/readyz") == (200, "ready")


def test_unknown_path_and_method_are_rejected():
    health = WorkerHealth()
    assert respond(health, "GET", "/")[0] == 404
    assert respond(health, "POST", "/livez")[0] == 405


def test_port_comes_from_the_agentarea_wf_namespace(monkeypatch):
    monkeypatch.setenv("AGENTAREA_WF_HEALTH_PORT", "9123")

    assert WorkerHealthSettings().HEALTH_PORT == 9123


async def _get(port: int, path: str) -> tuple[int, str]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
    await writer.drain()
    raw = await reader.read()
    writer.close()
    await writer.wait_closed()
    head, _, body = raw.decode().partition("\r\n\r\n")
    return int(head.split(" ", 2)[1]), body


async def test_server_answers_probes_over_http():
    health = WorkerHealth()
    server = HealthServer(health, host="127.0.0.1", port=0)
    await server.start()
    try:
        assert await _get(server.port, "/livez") == (200, "alive")
        assert (await _get(server.port, "/readyz"))[0] == 503

        health.mark_started({"agent-tasks": _Poller(True)})
        assert await _get(server.port, "/readyz") == (200, "ready")
    finally:
        await server.stop()


async def test_server_start_fails_loudly_when_port_is_taken():
    first = HealthServer(WorkerHealth(), host="127.0.0.1", port=0)
    await first.start()
    try:
        second = HealthServer(WorkerHealth(), host="127.0.0.1", port=first.port)
        with pytest.raises(OSError):
            await second.start()
    finally:
        await first.stop()


@activity.defn
async def _noop() -> None:
    return None


async def test_ready_tracks_a_real_temporal_worker_polling():
    env = await WorkflowEnvironment.start_time_skipping(download_dest_dir=temporal_download_dir())
    async with env:
        worker = Worker(env.client, task_queue=f"health-{uuid.uuid4()}", activities=[_noop])
        health = WorkerHealth()
        health.mark_started({"agent-tasks": worker})
        assert health.readiness()[0] is False

        run = asyncio.create_task(worker.run())
        for _ in range(100):
            if health.readiness()[0]:
                break
            await asyncio.sleep(0.05)
        assert health.readiness() == (True, "ready")

        await worker.shutdown()
        await run
        assert health.readiness()[0] is False
