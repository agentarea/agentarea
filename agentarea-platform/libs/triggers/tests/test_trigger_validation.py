"""Save-time rejection of a syntactically malformed condition body (#561)."""

from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerCreate
from agentarea_triggers.logging_utils import TriggerValidationError
from agentarea_triggers.trigger_validation import validate_trigger_configuration


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
