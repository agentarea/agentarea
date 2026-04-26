"""Trigger lifecycle + isolation (triggers depend on an agent)."""

from __future__ import annotations

import httpx
import pytest


def _create_agent(client: httpx.Client, name: str = "trigger-host") -> str:
    resp = client.post(
        "/v1/agents/",
        json={
            "name": name,
            "description": "for trigger test",
            "instruction": "respond",
            "model_id": "gpt-4",
            "agent_type": "chat",
        },
    )
    resp.raise_for_status()
    return resp.json()["id"]


@pytest.mark.integration
def test_trigger_lifecycle(alice_client: httpx.Client) -> None:
    agent_id = _create_agent(alice_client)

    created = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "t-lifecycle",
            "description": "lifecycle test",
            "agent_id": agent_id,
            "trigger_type": "webhook",
        },
    )
    assert created.status_code == 201, created.text[:200]
    trigger_id = created.json()["id"]

    fetched = alice_client.get(f"/v1/triggers/{trigger_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == trigger_id

    listed = alice_client.get("/v1/triggers/").json()
    listed = listed if isinstance(listed, list) else listed.get("items", [])
    assert any(t["id"] == trigger_id for t in listed)

    deleted = alice_client.delete(f"/v1/triggers/{trigger_id}")
    assert deleted.status_code in (200, 204)

    gone = alice_client.get(f"/v1/triggers/{trigger_id}")
    assert gone.status_code == 404


@pytest.mark.integration
def test_trigger_enable_disable(alice_client: httpx.Client) -> None:
    agent_id = _create_agent(alice_client, "trigger-toggle-host")
    trigger_id = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "t-toggle",
            "description": "toggle",
            "agent_id": agent_id,
            "trigger_type": "webhook",
        },
    ).raise_for_status().json()["id"]

    disabled = alice_client.post(f"/v1/triggers/{trigger_id}/disable")
    assert disabled.status_code in (200, 204), disabled.text[:200]
    state = alice_client.get(f"/v1/triggers/{trigger_id}").json()
    assert state["is_active"] is False

    enabled = alice_client.post(f"/v1/triggers/{trigger_id}/enable")
    assert enabled.status_code in (200, 204)
    state = alice_client.get(f"/v1/triggers/{trigger_id}").json()
    assert state["is_active"] is True


@pytest.mark.integration
def test_trigger_isolation(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_agent = _create_agent(alice_client, "alice-trigger-host")
    alice_trigger_id = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "alice-secret-trigger",
            "description": "isolation",
            "agent_id": alice_agent,
            "trigger_type": "webhook",
        },
    ).raise_for_status().json()["id"]

    cross_get = bob_client.get(f"/v1/triggers/{alice_trigger_id}")
    assert cross_get.status_code == 404, cross_get.text[:200]

    cross_del = bob_client.delete(f"/v1/triggers/{alice_trigger_id}")
    assert cross_del.status_code in (403, 404)

    bob_list = bob_client.get("/v1/triggers/").json()
    bob_list = bob_list if isinstance(bob_list, list) else bob_list.get("items", [])
    assert all(t["id"] != alice_trigger_id for t in bob_list)


@pytest.mark.integration
def test_trigger_rejects_other_users_agent(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    """Bob cannot create a trigger that points at Alice's agent."""
    alice_agent_id = _create_agent(alice_client, "alice-fortress")

    attack = bob_client.post(
        "/v1/triggers/",
        json={
            "name": "bob-attack",
            "description": "should fail",
            "agent_id": alice_agent_id,
            "trigger_type": "webhook",
        },
    )
    assert attack.status_code in (400, 403, 404), (
        f"CRITICAL: Bob created a trigger on Alice's agent: {attack.status_code} {attack.text[:200]}"
    )
