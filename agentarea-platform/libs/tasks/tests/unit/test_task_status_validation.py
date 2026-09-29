"""The task-status whitelist must accept every status the system actually sets.

`reserve_run` creates an attachment-staged task in `preparing`, and the workflow
parks tasks in `waiting_for_continuation` / `waiting_for_input`; if the validator
whitelist omits them, `_validate_task` rejects a legitimate task (the
/with-attachments endpoint 500'd on `Invalid task status: preparing`).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.base_service import BaseTaskService, TaskValidationError
from agentarea_tasks.domain.models import AgentTask


class _Service(BaseTaskService):
    async def submit_task(self, task: AgentTask) -> AgentTask:  # pragma: no cover
        raise NotImplementedError


def _task(status: str) -> AgentTask:
    now = datetime.utcnow()
    return AgentTask(
        id=uuid4(),
        title="t",
        description="d",
        query="q",
        user_id="user-1",
        agent_id=uuid4(),
        status=status,
        workspace_id="ws-1",
        created_at=now,
        updated_at=now,
    )


def _service() -> _Service:
    async def persist(task):
        task.user_id = "user-1"
        task.workspace_id = "ws-1"
        return task

    return _Service(
        task_repository=SimpleNamespace(create_task=AsyncMock(side_effect=persist)),
        event_broker=None,
        outbox_publisher=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "submitted",
        "pending",
        "preparing",
        "scheduled",
        "running",
        "working",
        "completed",
        "failed",
        "blocked",
        "cancelled",
        "waiting_for_continuation",
        "waiting_for_input",
        "waiting_for_approval",
    ],
)
async def test_task_creation_preserves_business_status(status: str) -> None:
    task = await _service().create_task(_task(status))

    assert task.status == status
    assert task.workspace_id == "ws-1"


@pytest.mark.asyncio
async def test_unknown_status_is_rejected() -> None:
    with pytest.raises(TaskValidationError):
        await _service().create_task(_task("not-a-real-status"))


def test_the_validator_reads_the_shared_vocabulary() -> None:
    """The whitelist and the list filter are one list, so neither can drift."""
    from agentarea_tasks.domain import base_service
    from agentarea_tasks.domain.statuses import TASK_STATUSES

    assert base_service.TASK_STATUSES is TASK_STATUSES
