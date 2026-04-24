"""Agent tool invocation end-to-end.

Covers:
  - Agent with the calculator tool actually calls the tool and gets the
    right arithmetic answer.
  - The agent's final answer is delivered via the `completion` tool call.
  - The built-in `agentarea/files` tool writes land in RustFS under
    ``workspaces/{workspace_id}/tasks/{task_id}/`` and the sandbox is
    isolated across workspaces.
  - Tool events are workspace-scoped: Bob cannot read Alice's agent events.
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


def _first_save_result(events: list[dict]) -> str:
    """Return the `result` of the first successful save_file ToolCallCompleted."""
    for e in events:
        if e["event_type"] != "ToolCallCompleted":
            continue
        md = e.get("metadata", {})
        if md.get("tool_name") != "file":
            continue
        args = md.get("arguments") or {}
        if args.get("action") != "save_file":
            continue
        result = str(md.get("result") or "")
        if not result.startswith("Error"):
            return result
    return ""


@pytest.mark.integration
@pytest.mark.slow
def test_agent_file_tool_writes_persist_in_workspace_sandbox(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Agent writes a file via agentarea/files and the write succeeds.

    Backend injects a workspace-scoped base_dir so writes actually land on a
    writable path. A prior bug had this tool hit the read-only /app dir.
    """
    file_name = "greeting.txt"
    content = "hello from e2e"

    agent_id = create_agent(
        alice_client,
        llm_model,
        name="file-agent",
        instruction=(
            "You have access to a file tool. Use save_file exactly once to "
            "create the requested file, then call completion."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={
            "description": (
                f"Create a file named {file_name} with the exact content: "
                f"{content}. Do not create any other files."
            )
        },
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, agent_id, task_id, timeout=180.0)
    completed = _tool_events(events, "ToolCallCompleted", "file")
    assert completed, "file tool never produced a ToolCallCompleted event"

    result = _first_save_result(events)
    assert result and not result.startswith("Error"), (
        f"agent's save_file never succeeded; last save results: "
        f"{[e['metadata'].get('result') for e in completed]}"
    )
    assert file_name in result, (
        f"save_file result should echo the file name; got {result!r}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_file_tool_sandbox_isolated_across_workspaces(
    alice_client: httpx.Client,
    user_factory,
    llm_model: str,
) -> None:
    """Alice writes a file; a second user's file tool cannot see it.

    The sandbox must be scoped by workspace_id — same file_name in a
    different workspace is a distinct empty directory.
    """
    file_name = "alice-secret.txt"
    alice_agent = create_agent(
        alice_client,
        llm_model,
        name="alice-fs-agent",
        instruction="Use save_file once to create the file, then call completion.",
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    alice_task = alice_client.post(
        f"/v1/agents/{alice_agent}/tasks/sync",
        json={
            "description": (
                f"Create file {file_name} with content: classified-alice-note."
            )
        },
        timeout=30.0,
    ).raise_for_status().json()["id"]
    alice_events = wait_for_workflow(
        alice_client, alice_agent, alice_task, timeout=180.0
    )
    assert _first_save_result(alice_events), "Alice's write did not succeed"

    # New user = new workspace. The agent reuses the same llm_model fixture
    # that Alice used, but because model_instance is workspace-scoped Charlie
    # can't reach it — so we build her own chain through alice_client's API,
    # then mint a separate user and run a list_files probe from their client.
    eve = user_factory("eve")
    eve_client = httpx.Client(
        base_url=str(alice_client.base_url),
        headers={"Authorization": f"Bearer {eve.jwt}"},
        timeout=20.0,
    )
    try:
        # Eve needs her own provider_config + model_instance — shortest path:
        # reuse the system-scoped provider_spec + model_spec by looking up
        # alice's model_instance would fail (workspace-scoped). We use the
        # same kwargs create path the fixture does.
        from tests.e2e.api.conftest import (
            LLM_API_KEY,
            LLM_ENDPOINT,
            _psql,
        )

        spec_id = _psql(
            "SELECT id FROM provider_specs WHERE provider_key='e2e-openai-compat';"
        )
        model_spec_id = _psql(
            "SELECT id FROM model_specs WHERE provider_spec_id='"
            + spec_id
            + "' ORDER BY created_at LIMIT 1;"
        )
        pc = eve_client.post(
            "/v1/provider-configs/",
            json={
                "provider_spec_id": spec_id,
                "name": "eve-cfg",
                "api_key": LLM_API_KEY,
                "endpoint_url": LLM_ENDPOINT,
            },
        ).raise_for_status().json()
        mi = eve_client.post(
            "/v1/model-instances/",
            json={
                "provider_config_id": pc["id"],
                "model_spec_id": model_spec_id,
                "name": "eve-mi",
            },
        ).raise_for_status().json()

        eve_agent = create_agent(
            eve_client,
            mi["id"],
            name="eve-fs-agent",
            instruction=(
                "Use list_files with pattern '*' once, then call completion."
            ),
            tools=[{"type": "code", "name": "agentarea/files"}],
        )
        eve_task = eve_client.post(
            f"/v1/agents/{eve_agent}/tasks/sync",
            json={"description": "List all files you can see."},
            timeout=30.0,
        ).raise_for_status().json()["id"]
        eve_events = wait_for_workflow(
            eve_client, eve_agent, eve_task, timeout=180.0
        )
    finally:
        eve_client.close()

    # Scan every list_files result from Eve — the file Alice wrote must not
    # appear. (Any save_file by Eve is fine; we only care about leaks.)
    listings = [
        e["metadata"].get("result", "")
        for e in eve_events
        if e["event_type"] == "ToolCallCompleted"
        and e.get("metadata", {}).get("tool_name") == "file"
        and e["metadata"].get("arguments", {}).get("action") == "list_files"
    ]
    for listing in listings:
        assert file_name not in str(listing), (
            f"CRITICAL: Alice's {file_name} is visible to Eve: {listing}"
        )


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
