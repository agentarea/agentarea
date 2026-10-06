"""Save-time rejection of a syntactically malformed condition body (#561)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerCreate, TriggerUpdate
from agentarea_triggers.logging_utils import TriggerValidationError
from agentarea_triggers.trigger_service import TriggerService
from agentarea_triggers.trigger_validation import validate_trigger_configuration

from .conftest import make_trigger_repository_factory


class _NoInstances:
    async def get_by_id(self, instance_id):
        return None


def _cron(conditions: dict) -> TriggerCreate:
    return TriggerCreate(
        name="Refunds",
        agent_id=uuid4(),
        trigger_type=TriggerType.CRON,
        cron_expression="0 9 * * *",
        task_parameters={"text": "check refunds"},
        conditions=conditions,
        created_by="u-1",
    )


@pytest.mark.parametrize(
    "conditions, message",
    [
        ({"type": "combined"}, "sub-condition"),
        ({"type": "combined", "conditions": []}, "sub-condition"),
        ({"type": "rule"}, "rule"),
        ({"type": "rule", "rules": []}, "rule"),
        ({"type": "rule", "rules": [{"field": "a", "operator": "eq", "value": 1}]}, "logic"),
        (
            {
                "type": "rule",
                "rules": [{"operator": "eq", "value": 1}],
                "logic": "AND",
            },
            "field",
        ),
    ],
)
async def test_a_syntactically_malformed_condition_is_refused_at_create(conditions, message):
    with pytest.raises(TriggerValidationError, match=message):
        await validate_trigger_configuration(_cron(conditions), _NoInstances())


async def test_a_well_formed_condition_is_accepted_at_create():
    conditions = {
        "type": "rule",
        "rules": [{"field": "priority", "operator": "eq", "value": "high"}],
        "logic": "AND",
    }
    await validate_trigger_configuration(_cron(conditions), _NoInstances())


async def test_no_conditions_configured_is_still_legitimate_at_create():
    """``{}`` means no filter was configured; it is not a malformed body."""
    await validate_trigger_configuration(_cron({}), _NoInstances())


def _service() -> TriggerService:
    return TriggerService(
        repository_factory=make_trigger_repository_factory(),
        event_broker=AsyncMock(),
        task_service=MagicMock(),
    )


@pytest.mark.parametrize(
    "conditions, message",
    [
        ({"type": "combined"}, "sub-condition"),
        ({"type": "combined", "conditions": []}, "sub-condition"),
        ({"type": "rule"}, "rule"),
        ({"type": "rule", "rules": []}, "rule"),
        ({"type": "rule", "rules": [{"field": "a", "operator": "eq", "value": 1}]}, "logic"),
    ],
)
async def test_a_syntactically_malformed_condition_is_refused_at_update(conditions, message):
    service = _service()
    existing_trigger = SimpleNamespace(id=uuid4())

    with pytest.raises(TriggerValidationError, match=message):
        await service._validate_trigger_update(
            existing_trigger, TriggerUpdate(conditions=conditions)
        )


async def test_a_well_formed_condition_is_accepted_at_update():
    service = _service()
    existing_trigger = SimpleNamespace(id=uuid4())
    conditions = {
        "type": "rule",
        "rules": [{"field": "priority", "operator": "eq", "value": "high"}],
        "logic": "AND",
    }

    await service._validate_trigger_update(existing_trigger, TriggerUpdate(conditions=conditions))


async def test_no_conditions_configured_is_still_legitimate_at_update():
    """``{}`` means no filter was configured; it is not a malformed body."""
    service = _service()
    existing_trigger = SimpleNamespace(id=uuid4())

    await service._validate_trigger_update(existing_trigger, TriggerUpdate(conditions={}))


async def test_an_update_that_does_not_touch_conditions_is_unchecked():
    """``conditions=None`` means the update leaves conditions alone, not that it clears them."""
    service = _service()
    existing_trigger = SimpleNamespace(id=uuid4())

    await service._validate_trigger_update(existing_trigger, TriggerUpdate(conditions=None))
