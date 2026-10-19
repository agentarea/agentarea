"""A trigger's stored task parameters cannot carry a delivery_address.

delivery_address names where replies go and whose credentials send them. Only a
stream firing may produce it, from the event and its source; a value stored in
``task_parameters`` would be copied onto every run.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import CronTrigger, TriggerCreate, TriggerUpdate
from agentarea_triggers.schemas import dto
from agentarea_triggers.trigger_service import TriggerService
from pydantic import ValidationError

FOREIGN_ADDRESS = {"type": "chat", "sender": "http", "credential_key": str(uuid4())}


def test_create_rejects_delivery_address_in_task_parameters():
    with pytest.raises(ValidationError, match="delivery_address"):
        TriggerCreate(
            name="nightly",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            cron_expression="0 0 * * *",
            created_by="member",
            task_parameters={"delivery_address": FOREIGN_ADDRESS},
        )


def test_update_drops_delivery_address_from_task_parameters():
    """A trigger stored before the check echoes the key back from the edit form."""
    update = TriggerUpdate(task_parameters={"delivery_address": FOREIGN_ADDRESS, "text": "report"})

    assert update.task_parameters == {"text": "report"}


def test_rest_and_toolset_create_payloads_reject_delivery_address():
    with pytest.raises(ValidationError, match="delivery_address"):
        dto.TriggerCreate(
            name="nightly",
            agent_id=uuid4(),
            trigger_type="cron",
            task_parameters={"delivery_address": FOREIGN_ADDRESS},
        )


def test_editing_a_legacy_trigger_through_the_rest_payload_drops_delivery_address():
    payload = dto.TriggerUpdate(
        task_parameters={"delivery_address": FOREIGN_ADDRESS, "text": "report"}
    )

    assert payload.to_domain().task_parameters == {"text": "report"}


@pytest.mark.asyncio
async def test_a_stored_delivery_address_is_not_copied_onto_the_run():
    service = TriggerService(repository_factory=AsyncMock(), event_broker=AsyncMock())
    trigger = CronTrigger(
        name="nightly",
        agent_id=uuid4(),
        created_by="member",
        cron_expression="0 0 * * *",
        task_parameters={"delivery_address": FOREIGN_ADDRESS, "instruction": "report"},
    )

    params = await service._build_task_parameters(trigger, {})

    assert "delivery_address" not in params
    assert params["instruction"] == "report"
