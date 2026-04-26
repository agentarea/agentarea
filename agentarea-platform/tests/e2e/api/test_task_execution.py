"""End-to-end task execution against a real OpenAI-compatible LLM endpoint.

The LLM target is configured via env vars in conftest:
  OPENAI_COMPAT_ENDPOINT  (default http://host.docker.internal:20128/v1)
  OPENAI_COMPAT_MODEL     (default kr/claude-sonnet-4.5)
  OPENAI_COMPAT_API_KEY   (default "" — backend skips Authorization header)

Works with any /v1/chat/completions provider (Omniroute, LiteLLM proxy,
vLLM, Ollama-openai, OpenAI itself, etc.).

The test drives the full happy path:
  agent create -> POST /tasks/sync -> poll /events for WorkflowCompleted
  -> assert an LLMCallCompleted event is present with content or a tool_call.
"""

from __future__ import annotations

import time

import httpx
import pytest


@pytest.mark.integration
@pytest.mark.slow
def test_task_executes_end_to_end(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = alice_client.post(
        "/v1/agents/",
        json={
            "name": "exec-agent",
            "description": "e2e execution test",
            "instruction": "Reply with exactly one lowercase word and nothing else.",
            "model_id": llm_model,
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
        if any(
            e["event_type"] in ("TaskFailed", "WorkflowFailed", "LLMCallFailed")
            for e in last_events
        ):
            pytest.fail(f"task failed: {[e['event_type'] for e in last_events]}")
        # Success = the workflow reached a completed iteration AND actually
        # invoked the LLM at least once (either got content back or chose a
        # tool call — both are valid outcomes of a real model round-trip).
        llm_completed = [
            e for e in last_events if e["event_type"] == "LLMCallCompleted"
        ]
        if llm_completed and any(
            e["event_type"] == "WorkflowCompleted" for e in last_events
        ):
            md = llm_completed[-1]["metadata"]
            assert md.get("content") is not None or md.get("tool_calls"), (
                f"LLMCallCompleted had neither content nor tool_calls: {md}"
            )
            return
        time.sleep(1.0)

    event_types = [e["event_type"] for e in last_events]
    pytest.fail(f"no WorkflowCompleted within 60s, saw events: {event_types}")


@pytest.mark.integration
def test_task_events_are_isolated(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_model: str,
) -> None:
    agent_id = alice_client.post(
        "/v1/agents/",
        json={
            "name": "iso-exec-agent",
            "description": "d",
            "instruction": "x",
            "model_id": llm_model,
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
