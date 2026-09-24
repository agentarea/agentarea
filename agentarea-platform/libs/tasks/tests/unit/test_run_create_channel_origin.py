"""A run's caller cannot supply channel_origin.

channel_origin names the trigger whose bot credentials the run's replies are
sent with. Only the trigger service produces it, from the trigger that
received the event.
"""

from uuid import uuid4

import pytest
from agentarea_tasks.schemas.dto import RunCreate
from pydantic import ValidationError


def test_run_create_rejects_channel_origin():
    with pytest.raises(ValidationError, match="channel_origin"):
        RunCreate(
            agent_id=uuid4(),
            description="hello",
            parameters={"channel_origin": {"type": "telegram", "trigger_id": str(uuid4())}},
        )


def test_run_create_keeps_other_parameters():
    run = RunCreate(agent_id=uuid4(), description="hello", parameters={"model_override": "x"})
    assert run.parameters == {"model_override": "x"}
