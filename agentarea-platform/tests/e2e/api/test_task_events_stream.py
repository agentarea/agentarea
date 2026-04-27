from __future__ import annotations

import json

import httpx
import pytest

from tests.e2e.api.conftest import create_agent


@pytest.mark.integration
@pytest.mark.slow
def test_task_events_stream_returns_sse(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="sse-task",
        instruction="Reply with exactly one lowercase word and nothing else.",
    )

    task = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Reply with the word: sse"},
        timeout=30.0,
    ).raise_for_status().json()
    task_id = task["id"]

    events = []
    with alice_client.stream(
        "GET",
        f"/v1/agents/{agent_id}/tasks/{task_id}/events/stream",
        timeout=120.0,
    ) as response:
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected SSE, got content-type={content_type}"
        )

        try:
            for line in response.iter_text():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        except httpx.ReadTimeout:
            pass

    assert events, "No SSE events received"
    types = [e.get("event_type") for e in events]
    assert "WorkflowCompleted" in types, (
        f"Expected WorkflowCompleted in SSE, got {types}"
    )


@pytest.mark.integration
def test_task_events_stream_cross_workspace_blocked(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_model: str,
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="sse-iso",
        instruction="ok.",
    )

    task = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "ok"},
        timeout=30.0,
    ).raise_for_status().json()
    task_id = task["id"]

    cross = bob_client.get(
        f"/v1/agents/{agent_id}/tasks/{task_id}/events/stream",
        timeout=10.0,
    )
    assert cross.status_code in (403, 404), (
        f"CRITICAL: Bob streamed Alice's task events: {cross.status_code} {cross.text[:200]}"
    )


@pytest.mark.integration
def test_task_events_stream_unknown_task_returns_404(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="sse-404",
        instruction="ok.",
    )

    resp = alice_client.get(
        f"/v1/agents/{agent_id}/tasks/00000000-0000-0000-0000-000000000000/events/stream",
        timeout=10.0,
    )
    assert resp.status_code == 404, resp.text[:200]
