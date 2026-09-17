"""Regression tests for automation edit payloads."""

from uuid import uuid4

from agentarea_triggers.schemas.dto import TriggerUpdate


def test_edit_payload_preserves_agent_task_and_events():
    agent_id = uuid4()
    payload = TriggerUpdate.model_validate(
        {
            "name": "Updated automation",
            "description": "Updated description",
            "agent_id": str(agent_id),
            "task_parameters": {"text": "Generate the weekly report", "budget": "2.50"},
            "event_types": ["message"],
        }
    )

    domain = payload.to_domain()

    assert domain.agent_id == agent_id
    assert domain.name == "Updated automation"
    assert domain.description == "Updated description"
    assert domain.task_parameters == payload.task_parameters
    assert domain.event_types == ["message"]


def test_edit_payload_can_clear_event_filter():
    assert TriggerUpdate(event_types=[]).to_domain().event_types == []


def test_omitted_agent_and_events_remain_unchanged():
    domain = TriggerUpdate(name="Renamed").to_domain()

    assert domain.agent_id is None
    assert domain.event_types is None
