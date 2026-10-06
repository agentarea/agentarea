"""Task parameters only a trigger writes are refused wherever a caller writes parameters.

``trigger_event`` and ``trigger_event_file`` make a run write a file into its
inputs, ``follow_up_message`` replaces what a routed follow-up says, and
``channel_origin`` borrows a trigger's bot. Every caller-facing surface that
takes task parameters -- a task, a run, a trigger's stored task parameters --
refuses them; an edit drops keys a trigger stored before the check.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_api.api.v1.agents_tasks import ScheduleTaskCreate, TaskCreate
from agentarea_tasks.schemas.dto import RunCreate
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import TriggerCreate as DomainTriggerCreate
from agentarea_triggers.domain.models import TriggerUpdate as DomainTriggerUpdate
from agentarea_triggers.schemas import dto
from pydantic import ValidationError

RESERVED = [
    {"trigger_event_file": "trigger-event-1.json", "trigger_event": {"a": 1}},
    {"trigger_event": {"a": 1}},
    {"follow_up_message": "hello"},
    {"channel_origin": {"chat_id": "1"}},
]


@pytest.mark.parametrize("reserved", RESERVED)
def test_a_task_or_run_refuses_reserved_parameters(reserved):
    with pytest.raises(ValidationError, match="cannot be supplied"):
        TaskCreate(description="d", parameters={"text": "x", **reserved})
    with pytest.raises(ValidationError, match="cannot be supplied"):
        ScheduleTaskCreate(
            description="d", parameters=reserved, scheduled_at=datetime.now(UTC) + timedelta(days=1)
        )
    with pytest.raises(ValidationError, match="cannot be supplied"):
        RunCreate(agent_id=uuid4(), description="d", parameters=reserved)


@pytest.mark.parametrize("reserved", RESERVED)
def test_a_trigger_refuses_reserved_task_parameters(reserved):
    with pytest.raises(ValidationError, match="cannot be supplied"):
        dto.TriggerCreate(
            name="n",
            agent_id=uuid4(),
            trigger_type="stream",
            stream_id=uuid4(),
            task_parameters={"text": "go", **reserved},
        )
    with pytest.raises(ValidationError, match="cannot be supplied"):
        DomainTriggerCreate(
            name="n",
            agent_id=uuid4(),
            trigger_type=TriggerType.CRON,
            cron_expression="0 0 * * *",
            created_by="u",
            task_parameters=reserved,
        )


def test_an_edit_drops_reserved_keys_a_trigger_stored_before_the_check():
    stored = {"text": "go", "trigger_event_file": "trigger-event-1.json", "follow_up_message": "x"}
    assert dto.TriggerUpdate(task_parameters=stored).to_domain().task_parameters == {"text": "go"}
    edit = DomainTriggerUpdate.model_validate({"task_parameters": stored})
    assert edit.task_parameters == {"text": "go"}


def test_ordinary_parameters_pass():
    assert RunCreate(
        agent_id=uuid4(), description="d", parameters={"trigger_data": {"x": 1}, "text": "t"}
    ).parameters == {"trigger_data": {"x": 1}, "text": "t"}
