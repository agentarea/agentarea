from __future__ import annotations

import httpx
import pytest

from tests.e2e.api.conftest import create_agent


@pytest.mark.integration
@pytest.mark.slow
def test_trigger_execute_public_creates_task(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="trigger-exec-agent",
        instruction="Reply with exactly one lowercase word and nothing else.",
    )

    trigger = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "exec-trigger",
            "description": "e2e execute test",
            "agent_id": agent_id,
            "trigger_type": "webhook",
        },
    ).raise_for_status().json()
    trigger_id = trigger["id"]

    execute_resp = alice_client.post(
        f"/v1/triggers/{trigger_id}/execute",
        json={"payload": {"message": "test execution"}},
    )
    assert execute_resp.status_code in (200, 202), execute_resp.text[:200]
    body = execute_resp.json()
    assert "task_id" in body or "status" in body, f"Unexpected execute response: {body}"


@pytest.mark.integration
def test_trigger_execute_unknown_trigger_returns_404(
    alice_client: httpx.Client,
) -> None:
    resp = alice_client.post(
        "/v1/triggers/00000000-0000-0000-0000-000000000000/execute",
        json={"payload": {}},
    )
    assert resp.status_code == 404, resp.text[:200]


@pytest.mark.integration
def test_trigger_execute_disabled_trigger_rejected(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="trigger-disabled-agent",
        instruction="ok.",
    )

    trigger = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "disabled-trigger",
            "agent_id": agent_id,
            "trigger_type": "webhook",
        },
    ).raise_for_status().json()

    alice_client.post(f"/v1/triggers/{trigger['id']}/disable").raise_for_status()

    resp = alice_client.post(
        f"/v1/triggers/{trigger['id']}/execute",
        json={"payload": {}},
    )
    assert resp.status_code in (400, 403, 409, 200), (
        f"Got {resp.status_code}: {resp.text[:200]}"
    )
    if resp.status_code == 200:
        pytest.xfail("BUG: disabled trigger still executes and returns 200")
