"""Tests for the broker-neutral event-bus contract (ADR-0018)."""

from agentarea_common.events.ports import IntegrationEvent


def test_partition_key_uses_subject():
    evt = IntegrationEvent(
        type="agentarea.agents.v1.AgentDeleted",
        source="agentarea-api",
        subject="agent-123",
    )
    assert evt.partition_key == "agent-123"


def test_partition_key_falls_back_to_id():
    evt = IntegrationEvent(type="agentarea.agents.v1.AgentDeleted", source="agentarea-api")
    assert evt.partition_key == str(evt.id)


def test_cloudevents_defaults():
    evt = IntegrationEvent(type="x.y.v1.Z", source="svc")
    assert evt.specversion == "1.0"
    assert evt.datacontenttype == "application/json"
    assert evt.data == {}
    assert evt.id is not None
    assert evt.time is not None


def test_roundtrips_through_json():
    evt = IntegrationEvent(
        type="agentarea.agents.v1.AgentDeleted",
        source="agentarea-api",
        subject="agent-123",
        data={"agent_id": "agent-123", "workspace_id": "ws-1"},
        correlation_id="req-1",
    )
    restored = IntegrationEvent.model_validate_json(evt.model_dump_json())
    assert restored == evt
