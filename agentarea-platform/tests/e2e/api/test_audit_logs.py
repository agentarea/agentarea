"""Audit log: actions are recorded and are workspace-scoped."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.integration
def test_agent_create_emits_audit_event(alice_client: httpx.Client) -> None:
    agent_id = alice_client.post(
        "/v1/agents/",
        json={
            "name": "audit-agent",
            "description": "d",
            "instruction": "i",
            "model_id": "gpt-4",
            "agent_type": "chat",
        },
    ).raise_for_status().json()["id"]

    events = alice_client.get("/v1/audit-logs/").raise_for_status().json()["events"]

    matching = [
        e
        for e in events
        if e["action"] == "agent.create"
        and e["resource_type"] == "agent"
        and e["resource_id"] == agent_id
    ]
    assert len(matching) == 1, (
        f"Expected exactly one agent.create audit event for {agent_id}, got {len(matching)}"
    )
    assert matching[0]["actor_type"] == "user"


@pytest.mark.integration
def test_audit_logs_are_workspace_scoped(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_agent_id = alice_client.post(
        "/v1/agents/",
        json={
            "name": "audit-leak-agent",
            "description": "d",
            "instruction": "i",
            "model_id": "gpt-4",
            "agent_type": "chat",
        },
    ).raise_for_status().json()["id"]

    bob_events = bob_client.get("/v1/audit-logs/").raise_for_status().json()["events"]
    assert all(
        e["resource_id"] != alice_agent_id for e in bob_events
    ), "CRITICAL: Bob sees Alice's audit event"

    bob_events = [e for e in bob_events if e["action"] == "agent.create"]
    for e in bob_events:
        assert e["actor_id"] != alice_agent_id  # actor never hers
