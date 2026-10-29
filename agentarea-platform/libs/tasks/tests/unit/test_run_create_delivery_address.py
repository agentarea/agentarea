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
    run = RunCreate(agent_id=uuid4(), description="hello", parameters={"topic": "x"})
    assert run.parameters == {"topic": "x"}


def test_a_model_override_must_name_a_model_instance():
    with pytest.raises(ValidationError, match="model instance id"):
        RunCreate(agent_id=uuid4(), description="hi", parameters={"model_override": "gpt-4o"})

    run = RunCreate(
        agent_id=uuid4(),
        description="hi",
        parameters={"model_override": "aad7c8d9-756e-58e0-b42f-80ba341616df"},
    )
    assert run.parameters["model_override"] == "aad7c8d9-756e-58e0-b42f-80ba341616df"
