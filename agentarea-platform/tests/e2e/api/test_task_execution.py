"""End-to-end task execution against a real LLM (local Omniroute router).

Requires:
  - Omniroute reachable at http://host.docker.internal:20128 from the backend
    container (default; override via OMNIROUTE_ENDPOINT).
  - Model `kr/claude-sonnet-4.5` available on the router (override via
    OMNIROUTE_MODEL).

The test drives the full happy path:
  agent create -> POST /tasks/sync -> poll /events for LLMCallCompleted
  -> assert the assistant message is present.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("OMNIROUTE_API_KEY"),
    reason="OMNIROUTE_API_KEY not set — skipping real LLM round-trip",
)
def test_task_executes_end_to_end(
    alice_client: httpx.Client, omniroute_model: str
) -> None:
    agent_id = alice_client.post(
        "/v1/agents/",
        json={
            "name": "exec-agent",
            "description": "e2e execution test",
            "instruction": "Reply with exactly one lowercase word and nothing else.",
            "model_id": omniroute_model,
            "agent_type": "chat",
        },
    ).raise_for_status().json()["id"]

    task = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Reply with the single word: ok"},
        timeout=30.0,
    )
    assert task.status_code == 200, task.text[:200]
    task_id = task.json()["id"]

    deadline = time.time() + 60.0
    last_events: list[dict] = []
    while time.time() < deadline:
        events_resp = alice_client.get(
            f"/v1/agents/{agent_id}/tasks/{task_id}/events"
        )
        events_resp.raise_for_status()
        last_events = events_resp.json()["events"]
        completions = [
            e for e in last_events if e["event_type"] == "LLMCallCompleted"
        ]
        if completions:
            content = completions[-1]["metadata"]["content"]
            assert content, "model returned empty content"
            return
        if any(
            e["event_type"] in ("TaskFailed", "WorkflowFailed") for e in last_events
        ):
            pytest.fail(f"task failed: {last_events}")
        time.sleep(1.0)

    event_types = [e["event_type"] for e in last_events]
    pytest.fail(f"no LLMCallCompleted within 60s, saw events: {event_types}")


@pytest.mark.integration
def test_task_events_are_isolated(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    omniroute_model: str,
) -> None:
    agent_id = alice_client.post(
        "/v1/agents/",
        json={
            "name": "iso-exec-agent",
            "description": "d",
            "instruction": "x",
            "model_id": omniroute_model,
            "agent_type": "chat",
        },
    ).raise_for_status().json()["id"]

    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "ok"},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    cross_events = bob_client.get(
        f"/v1/agents/{agent_id}/tasks/{task_id}/events"
    )
    assert cross_events.status_code in (403, 404), cross_events.text[:200]
