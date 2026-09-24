"""A trigger's stored task parameters cannot carry a channel_origin.

channel_origin names the trigger whose bot credentials replies go out with.
Only ``_build_channel_origin`` may produce it, from the trigger that received
the event; a value stored in ``task_parameters`` was copied onto every run.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import CronTrigger, TriggerCreate, TriggerUpdate
from agentarea_triggers.schemas import dto
from agentarea_triggers.trigger_service import TriggerService
from pydantic import ValidationError

FOREIGN_ORIGIN = {"type": "telegram", "trigger_id": str(uuid4()), "chat_id": "1"}


def test_create_rejects_channel_origin_in_task_parameters():
    with pytest.raises(ValidationError, match="channel_origin"):
        TriggerCreate(
            name="nightly",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            cron_expression="0 0 * * *",
            created_by="member",
            task_parameters={"channel_origin": FOREIGN_ORIGIN},
        )


def test_update_rejects_channel_origin_in_task_parameters():
    with pytest.raises(ValidationError, match="channel_origin"):
        TriggerUpdate(task_parameters={"channel_origin": FOREIGN_ORIGIN})


def test_rest_and_toolset_payloads_reject_channel_origin():
    with pytest.raises(ValidationError, match="channel_origin"):
        dto.TriggerCreate(
            name="nightly",
            agent_id=uuid4(),
            trigger_type="cron",
            task_parameters={"channel_origin": FOREIGN_ORIGIN},
        )
    with pytest.raises(ValidationError, match="channel_origin"):
        dto.TriggerUpdate(task_parameters={"channel_origin": FOREIGN_ORIGIN})


@pytest.mark.asyncio
async def test_a_stored_channel_origin_is_not_copied_onto_the_run():
    service = TriggerService(repository_factory=AsyncMock(), event_broker=AsyncMock())
    trigger = CronTrigger(
        name="nightly",
        agent_id=uuid4(),
        created_by="member",
        cron_expression="0 0 * * *",
        task_parameters={"channel_origin": FOREIGN_ORIGIN, "instruction": "report"},
    )

    params = await service._build_task_parameters(trigger, {})

    assert "channel_origin" not in params
    assert params["instruction"] == "report"
