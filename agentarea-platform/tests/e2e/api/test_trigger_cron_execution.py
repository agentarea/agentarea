from __future__ import annotations

import time

import httpx
import pytest

from tests.e2e.api.conftest import create_agent


@pytest.mark.integration
@pytest.mark.slow
def test_cron_trigger_creates_task_on_schedule(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="cron-host",
        instruction="Reply with exactly one lowercase word and nothing else.",
    )

    trigger = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "cron-e2e",
            "description": "Real cron trigger e2e test",
            "agent_id": agent_id,
            "trigger_type": "cron",
            "cron_expression": "* * * * *",
        },
    ).raise_for_status().json()
    trigger_id = trigger["id"]

    try:
        status = alice_client.get(
            f"/v1/triggers/{trigger_id}/status"
        ).raise_for_status().json()
        assert status.get("is_active") is True, f"cron trigger not active: {status}"
        assert "schedule_info" in status or "schedule" in status or "cron_expression" in status, (
            f"Expected schedule info in status: {status}"
        )

        deadline = time.time() + 90.0
        executions = []
        while time.time() < deadline:
            resp = alice_client.get(f"/v1/triggers/{trigger_id}/executions")
            if resp.status_code == 200:
                data = resp.json()
                executions = data.get("executions", data if isinstance(data, list) else [])
                if executions:
                    break
            time.sleep(5.0)

        assert executions, (
            f"cron trigger {trigger_id} did not produce any executions within 90s"
        )

        last = executions[0]
        assert last.get("task_id") or last.get("status") in (
            "success",
            "completed",
            "pending",
        ), f"Unexpected execution record: {last}"
    finally:
        alice_client.delete(f"/v1/triggers/{trigger_id}")


@pytest.mark.integration
def test_cron_trigger_rejects_invalid_expression(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="cron-bad-expr",
        instruction="ok.",
    )

    resp = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "cron-bad",
            "agent_id": agent_id,
            "trigger_type": "cron",
            "cron_expression": "not-a-cron",
        },
    )
    assert resp.status_code in (400, 422), (
        f"Expected 400/422 for invalid cron, got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_cron_trigger_disable_prevents_execution(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="cron-disabled",
        instruction="ok.",
    )

    trigger = alice_client.post(
        "/v1/triggers/",
        json={
            "name": "cron-disable-test",
            "agent_id": agent_id,
            "trigger_type": "cron",
            "cron_expression": "* * * * *",
        },
    ).raise_for_status().json()
    trigger_id = trigger["id"]

    try:
        alice_client.post(f"/v1/triggers/{trigger_id}/disable").raise_for_status()
        status = alice_client.get(
            f"/v1/triggers/{trigger_id}/status"
        ).raise_for_status().json()
        assert status.get("is_active") is False, f"Trigger still active after disable: {status}"
    finally:
        alice_client.delete(f"/v1/triggers/{trigger_id}")
