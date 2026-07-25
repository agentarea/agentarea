"""The task-status whitelist must accept every status the system actually sets.

`reserve_run` creates an attachment-staged task in `preparing`, and the workflow
parks tasks in `waiting_for_continuation` / `waiting_for_input`; if the validator
whitelist omits them, `_validate_task` rejects a legitimate task (the
/with-attachments endpoint 500'd on `Invalid task status: preparing`).
"""

from __future__ import annotations

from datetime import datetime
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
    return _Service(task_repository=None, event_broker=None, outbox_publisher=None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "submitted",
        "pending",
        "preparing",
        "running",
        "working",
        "completed",
        "failed",
        "blocked",
        "cancelled",
        "waiting_for_continuation",
        "waiting_for_input",
    ],
)
async def test_every_real_status_validates(status: str) -> None:
    await _service()._validate_task(_task(status))  # must not raise


@pytest.mark.asyncio
async def test_unknown_status_is_rejected() -> None:
    with pytest.raises(TaskValidationError):
        await _service()._validate_task(_task("not-a-real-status"))
