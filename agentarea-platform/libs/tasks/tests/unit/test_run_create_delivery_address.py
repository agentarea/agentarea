"""A run's caller cannot supply delivery_address.

delivery_address names the source whose credentials the run's replies are sent
with. Only a stream firing produces it, from the event and its source.
"""

from uuid import uuid4

import pytest
from agentarea_tasks.schemas.dto import RunCreate
from pydantic import ValidationError


def test_run_create_rejects_delivery_address():
    with pytest.raises(ValidationError, match="delivery_address"):
        RunCreate(
            agent_id=uuid4(),
            description="hello",
            parameters={"delivery_address": {"type": "chat", "credential_key": str(uuid4())}},
        )


def test_run_create_keeps_other_parameters():
    run = RunCreate(agent_id=uuid4(), description="hello", parameters={"model_override": "x"})
    assert run.parameters == {"model_override": "x"}
