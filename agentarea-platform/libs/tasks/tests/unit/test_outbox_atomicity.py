"""The outbox row must be covered by the aggregate write's commit.

The repository commits its own transaction. An event enqueued after that call
is therefore NOT part of it: the guarantee the outbox exists for — the event
and the state change land together or not at all — is lost, and a crash in
between drops the event silently. Enqueueing first, on the same session, puts
the row inside the commit the repository is about to make.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_tasks.domain.base_service import BaseTaskService
from agentarea_tasks.domain.models import AgentTask


class _RecordingRepository:
    def __init__(self, calls: list[str], fail: bool = False) -> None:
        self._calls = calls
        self._fail = fail

    async def update_task(self, task_domain):
        self._calls.append("aggregate-write")
        if self._fail:
            raise RuntimeError("aggregate write failed")
        return task_domain


class _RecordingOutbox:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.events: list[object] = []

    async def publish(self, event) -> None:
        self._calls.append("outbox-enqueue")
        self.events.append(event)


class _Service(BaseTaskService):
    async def submit_task(self, task: AgentTask) -> AgentTask:  # pragma: no cover
        raise NotImplementedError


def _task(status: str = "running") -> AgentTask:
    return AgentTask(
        id=uuid4(),
        title="t",
        description="d",
        query="q",
        user_id="user-1",
        agent_id=uuid4(),
        status=status,
        workspace_id="ws-1",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _service(calls: list[str], fail: bool = False):
    outbox = _RecordingOutbox(calls)
    service = _Service(
        task_repository=_RecordingRepository(calls, fail=fail),
        event_broker=None,
        outbox_publisher=outbox,
    )
    return service, outbox


@pytest.mark.asyncio
async def test_event_is_enqueued_before_the_aggregate_write(monkeypatch):
    calls: list[str] = []
    service, outbox = _service(calls)
    task = _task()
    monkeypatch.setattr(service, "_validate_task", _noop)
    monkeypatch.setattr(service, "get_task", _existing(task, "pending"))

    await service.update_task(task)

    assert calls, "nothing ran"
    assert calls[-1] == "aggregate-write", (
        "the write must come last so its commit covers the outbox rows"
    )
    assert "outbox-enqueue" in calls[:-1]


@pytest.mark.asyncio
async def test_a_failed_write_leaves_no_event_behind(monkeypatch):
    # The rows were added to the same session, so the repository's rollback
    # discards them: no event escapes for a change that never landed.
    calls: list[str] = []
    service, outbox = _service(calls, fail=True)
    task = _task()
    monkeypatch.setattr(service, "_validate_task", _noop)
    monkeypatch.setattr(service, "get_task", _existing(task, "pending"))

    with pytest.raises(RuntimeError):
        await service.update_task(task)

    assert calls[-1] == "aggregate-write"


@pytest.mark.asyncio
async def test_status_change_event_also_precedes_the_write(monkeypatch):
    calls: list[str] = []
    service, outbox = _service(calls)
    task = _task(status="completed")
    monkeypatch.setattr(service, "_validate_task", _noop)
    monkeypatch.setattr(service, "get_task", _existing(task, "running"))

    await service.update_task(task)

    assert calls.count("outbox-enqueue") == 2, "TaskUpdated + TaskStatusChanged"
    assert calls[-1] == "aggregate-write"


async def _noop(*args, **kwargs):
    return None


def _existing(task: AgentTask, status: str):
    async def _get(_task_id):
        existing = task.model_copy()
        existing.status = status
        return existing

    return _get
