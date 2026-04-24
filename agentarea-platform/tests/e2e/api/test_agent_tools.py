"""Agent tool invocation end-to-end.

Covers:
  - Agent with the calculator tool actually calls the tool and gets the
    right arithmetic answer.
  - The agent's final answer is delivered via the `completion` tool call.
  - A built-in tool fires ToolCallStarted + ToolCallCompleted events with
    observable arguments and results.
  - Tool events are workspace-scoped: Bob cannot read Alice's agent events.

The built-in `agentarea/files` tool currently writes to the backend
container's /app directory (read-only) — writes fail with Permission
denied. The file test therefore only asserts the tool is *reachable*
(ToolCallCompleted fires), not that a file is persisted. Tightening to a
real roundtrip requires wiring the tool to RustFS or a project directory.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.e2e.api.conftest import create_agent, wait_for_workflow


def _tool_events(events: list[dict], event_type: str, tool_name: str) -> list[dict]:
    return [
        e
        for e in events
        if e["event_type"] == event_type
        and e.get("metadata", {}).get("tool_name") == tool_name
    ]


def _completion_args(events: list[dict]) -> dict | None:
    """Extract the arguments from the final `completion` tool call, if any."""
    for e in reversed(events):
        if e["event_type"] != "LLMCallCompleted":
            continue
        for tc in e.get("metadata", {}).get("tool_calls", []):
            fn = tc.get("function") or tc
            if (fn.get("name") or tc.get("name")) == "completion":
                raw = fn.get("arguments") or tc.get("arguments") or "{}"
                return json.loads(raw) if isinstance(raw, str) else raw
    return None


@pytest.mark.integration
@pytest.mark.slow
def test_agent_uses_calculator_tool(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="calc-agent",
        instruction=(
            "Use the calculator tool for arithmetic. "
            "After you have the result, call completion with just the number."
        ),
        tools=[{"type": "code", "name": "agentarea/calculator"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "What is 17 * 23? Use the calculator."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, agent_id, task_id)
    assert any(e["event_type"] == "WorkflowCompleted" for e in events), (
        f"expected WorkflowCompleted; got {[e['event_type'] for e in events]}"
    )

    calc_completed = _tool_events(events, "ToolCallCompleted", "calculate")
    assert calc_completed, "calculator tool was never invoked"
    result_text = str(calc_completed[-1]["metadata"].get("result") or "")
    assert "391" in result_text, f"calculator produced wrong result: {result_text!r}"


@pytest.mark.integration
@pytest.mark.slow
def test_agent_completion_tool_delivers_final_answer(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="completion-agent",
        instruction=(
            "When asked a question, call the completion tool with the answer "
            "as a single word."
        ),
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "What colour is the sky on a clear day? One word."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, agent_id, task_id)
    args = _completion_args(events)
    assert args is not None, (
        f"expected a completion tool_call; got {[e['event_type'] for e in events]}"
    )
    answer = (args.get("result") or args.get("answer") or "").lower()
    assert "blue" in answer, f"expected 'blue' in final answer, got {answer!r}"


@pytest.mark.integration
@pytest.mark.slow
def test_agent_file_tool_is_reachable(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Calls into the built-in files tool are dispatched end-to-end.

    Does NOT assert persistence — the tool currently writes to the backend
    container FS where /app is read-only. We only check that ToolCallStarted
    and ToolCallCompleted events fire for the `file` tool.
    """
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="file-agent",
        instruction=(
            "You have access to a file tool. When asked to create a file, "
            "call it once. Then call completion with any short status message."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Create a file note.txt with content 'hello'."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(
        alice_client, agent_id, task_id, timeout=180.0
    )
    started = _tool_events(events, "ToolCallStarted", "file")
    completed = _tool_events(events, "ToolCallCompleted", "file")
    assert started, "file tool was never started"
    assert completed, "file tool never produced a ToolCallCompleted event"


@pytest.mark.integration
@pytest.mark.slow
def test_tool_events_are_workspace_scoped(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_model: str,
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="iso-tool-agent",
        instruction="Call calculator then completion.",
        tools=[{"type": "code", "name": "agentarea/calculator"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "2 + 2 = ?"},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    cross = bob_client.get(
        f"/v1/agents/{agent_id}/tasks/{task_id}/events"
    )
    assert cross.status_code in (403, 404), (
        f"CRITICAL: Bob can read Alice's agent's tool events: {cross.status_code}"
    )
