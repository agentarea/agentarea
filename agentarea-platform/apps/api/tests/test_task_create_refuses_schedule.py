"""A task started now never quietly drops a requested start time."""

from datetime import UTC, datetime, timedelta

import pytest
from agentarea_api.api.v1.agents_tasks import ScheduleTaskCreate, TaskCreate
from pydantic import ValidationError

LATER = (datetime.now(UTC) + timedelta(days=1)).isoformat()


def test_an_immediate_task_refuses_a_start_time():
    with pytest.raises(ValidationError, match="tasks/schedule"):
        TaskCreate.model_validate({"description": "send the digest", "scheduled_at": LATER})


def test_a_scheduled_task_still_takes_one():
    task = ScheduleTaskCreate.model_validate(
        {"description": "send the digest", "scheduled_at": LATER}
    )

    assert task.scheduled_at > datetime.now(UTC)


def test_an_immediate_task_without_one_is_unchanged():
    assert (
        TaskCreate.model_validate({"description": "send the digest"}).description
        == "send the digest"
    )
