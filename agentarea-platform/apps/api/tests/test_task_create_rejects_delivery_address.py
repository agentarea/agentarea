"""POST /v1/agents/{id}/tasks refuses a caller-supplied delivery_address.

It names the source whose credentials replies are sent with, so a member could
otherwise answer through another source's bot.
"""

from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import ScheduleTaskCreate, TaskCreate
from pydantic import ValidationError

ADDRESS = {"type": "chat", "sender": "http", "credential_key": str(uuid4())}


def test_task_create_rejects_delivery_address():
    with pytest.raises(ValidationError, match="delivery_address"):
        TaskCreate(description="hi", parameters={"delivery_address": ADDRESS})


def test_scheduled_task_create_rejects_delivery_address():
    with pytest.raises(ValidationError, match="delivery_address"):
        ScheduleTaskCreate.model_validate(
            {
                "description": "hi",
                "parameters": {"delivery_address": ADDRESS},
                "scheduled_at": "2999-01-01T00:00:00+00:00",
            }
        )
