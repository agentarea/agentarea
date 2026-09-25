"""POST /v1/agents/{id}/tasks refuses a caller-supplied channel_origin.

It names the trigger whose bot credentials replies are sent with, so a member
could otherwise answer through another workspace's bot.
"""

from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import ScheduleTaskCreate, TaskCreate
from pydantic import ValidationError

ORIGIN = {"type": "telegram", "trigger_id": str(uuid4()), "chat_id": "1"}


def test_task_create_rejects_channel_origin():
    with pytest.raises(ValidationError, match="channel_origin"):
        TaskCreate(description="hi", parameters={"channel_origin": ORIGIN})


def test_scheduled_task_create_rejects_channel_origin():
    with pytest.raises(ValidationError, match="channel_origin"):
        ScheduleTaskCreate.model_validate(
            {
                "description": "hi",
                "parameters": {"channel_origin": ORIGIN},
                "scheduled_at": "2999-01-01T00:00:00+00:00",
            }
        )
