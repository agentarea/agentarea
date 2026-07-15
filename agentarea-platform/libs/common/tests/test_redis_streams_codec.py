"""Codec tests for the Redis Streams event-bus adapter (ADR-0018)."""

from agentarea_common.events.adapters.redis_streams import decode, encode, topic_for
from agentarea_common.events.ports import IntegrationEvent


def test_topic_for():
    assert topic_for("agentarea.agents.v1.AgentDeleted") == "events:agentarea.agents.v1.AgentDeleted"


def test_encode_fields_are_all_strings():
    evt = IntegrationEvent(
        type="agentarea.agents.v1.AgentDeleted",
        source="agentarea-api",
        subject="agent-1",
        data={"agent_id": "agent-1"},
    )
    fields = encode(evt)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items())
    assert fields["ce_type"] == "agentarea.agents.v1.AgentDeleted"
    assert fields["ce_subject"] == "agent-1"


def test_optional_fields_omitted_when_none():
    evt = IntegrationEvent(type="x.y.v1.Z", source="svc")
    fields = encode(evt)
    assert "ce_subject" not in fields
    assert "ce_correlationid" not in fields


def test_encode_decode_roundtrip():
    evt = IntegrationEvent(
        type="agentarea.agents.v1.AgentDeleted",
        source="agentarea-api",
        subject="agent-1",
        correlation_id="req-1",
        data={"agent_id": "agent-1", "workspace_id": "ws-1"},
    )
    restored = decode(encode(evt))
    assert restored.id == evt.id
    assert restored.type == evt.type
    assert restored.subject == evt.subject
    assert restored.correlation_id == evt.correlation_id
    assert restored.data == evt.data
