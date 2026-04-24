"""Agent tool invocation end-to-end.

Covers:
  - Agent with the calculator tool actually calls the tool and gets the
    right arithmetic answer.
  - The agent's final answer is delivered via the `completion` tool call.
  - The built-in `agentarea/files` tool writes land in RustFS under
    ``workspaces/{workspace_id}/tasks/{task_id}/`` and the sandbox is
    isolated across workspaces. A real agent task writes a file; the test
    then reads the bytes back directly from RustFS via ArtifactService to
    prove the full agent -> activity -> S3 chain.
  - Tool events are workspace-scoped: Bob cannot read Alice's agent events.
"""

from __future__ import annotations

import asyncio
import json
import os

import httpx
import pytest

from tests.e2e.api.conftest import _psql, create_agent, wait_for_workflow


def _rustfs_env_defaults() -> None:
    """Point ArtifactService at the local RustFS the backend also uses.

    Test runs on the host, the backend container runs against
    ``http://rustfs:9000``; from the host we reach it at localhost:9000.
    """
    os.environ.setdefault("AWS_ENDPOINT_URL", "http://localhost:9000")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "rustfsadmin")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "rustfsadmin")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("ARTIFACTS_BUCKET_NAME", "artifacts")


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
    """Agent writes a file via ``agentarea/files`` and the bytes land in RustFS.

    This is the load-bearing proof that the full chain works end-to-end:

        agent → activity → ArtifactService → RustFS

    After the agent's task completes, we connect to RustFS directly (via
    ``ArtifactService``) and read the object back. The assertion is on the
    actual stored bytes, not on the tool's success string — a tool returning
    "Saved 'greeting.txt'" proves nothing about what reached the bucket.
    """
    _rustfs_env_defaults()
    from agentarea_common.artifacts import ArtifactService

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

    # The task row owns workspace_id; the activity scopes the file tool
    # under tasks/{task_id}/, so the object key in RustFS is
    #   workspaces/{workspace_id}/tasks/{task_id}/{file_name}
    workspace_id = _psql(f"SELECT workspace_id FROM tasks WHERE id='{task_id}';")
    assert workspace_id, f"task {task_id} missing workspace_id"

    svc = ArtifactService()
    artifact_path = f"tasks/{task_id}/{file_name}"
    try:
        assert asyncio.run(svc.exists(workspace_id, artifact_path)), (
            f"expected artifact at workspaces/{workspace_id}/{artifact_path} "
            f"in bucket {svc.bucket!r}, but it is not there"
        )
        data, _ = asyncio.run(svc.get(workspace_id, artifact_path))
        decoded = data.decode("utf-8", errors="replace")
        assert content in decoded, (
            f"artifact bytes do not contain the requested content; "
            f"expected substring {content!r}, got {decoded!r}"
        )
    finally:
        try:
            asyncio.run(svc.delete(workspace_id, artifact_path))
        except Exception:  # best-effort cleanup, never mask assertion failure
            pass


@pytest.mark.integration
@pytest.mark.slow
def test_agent_file_tool_round_trip_read_after_write(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Agent writes a file, reads it back, and returns the content — within one task.

    Exercises both halves of the tool against the same RustFS scope in a
    single workflow:

        save_file("secret.txt", sentinel) → read_file("secret.txt") → completion(result=<bytes>)

    The test then also pulls the bytes directly from RustFS via
    ArtifactService to triple-check nothing lied along the way.
    """
    _rustfs_env_defaults()
    from agentarea_common.artifacts import ArtifactService

    file_name = "secret.txt"
    sentinel = "artichoke-42-zebra"

    agent_id = create_agent(
        alice_client,
        llm_model,
        name="file-rw-agent",
        instruction=(
            "You have a file tool. Do EXACTLY this sequence in order:\n"
            "  1. save_file to create the requested file with the requested content.\n"
            "  2. read_file on the same file.\n"
            "  3. completion with a single-field JSON {\"result\": <text you just read>}.\n"
            "Never skip steps; never invent content."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={
            "description": (
                f"Create file {file_name} with exact content: {sentinel}. "
                f"Then read it and return what you read."
            )
        },
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, agent_id, task_id, timeout=180.0)

    # Tool layer: the save AND the read both succeeded.
    tool_events = _tool_events(events, "ToolCallCompleted", "file")
    actions = [
        (e["metadata"].get("arguments") or {}).get("action") for e in tool_events
    ]
    assert "save_file" in actions, f"save_file never invoked; got {actions!r}"
    assert "read_file" in actions, f"read_file never invoked; got {actions!r}"

    read_events = [
        e for e in tool_events
        if (e["metadata"].get("arguments") or {}).get("action") == "read_file"
    ]
    assert read_events, "no read_file ToolCallCompleted event"
    read_result = str(read_events[0]["metadata"].get("result") or "")
    assert not read_result.startswith("Error"), (
        f"agent's read_file returned an error: {read_result!r}"
    )
    assert sentinel in read_result, (
        f"read_file did not return the bytes the agent just wrote; "
        f"expected {sentinel!r} in {read_result!r}"
    )

    # Completion layer: the agent echoed the content back to the user.
    args = _completion_args(events)
    assert args is not None, "agent never called completion"
    final = str(args.get("result") or args.get("answer") or "")
    assert sentinel in final, (
        f"completion args should contain the round-tripped content; got {final!r}"
    )

    # Storage layer: the bytes really landed in RustFS, under this task's scope.
    workspace_id = _psql(f"SELECT workspace_id FROM tasks WHERE id='{task_id}';")
    svc = ArtifactService()
    artifact_path = f"tasks/{task_id}/{file_name}"
    try:
        data, _ = asyncio.run(svc.get(workspace_id, artifact_path))
        assert sentinel in data.decode("utf-8", errors="replace"), (
            f"RustFS object contents don't match what the agent saved"
        )
    finally:
        try:
            asyncio.run(svc.delete(workspace_id, artifact_path))
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.slow
def test_agent_file_tool_lists_its_own_writes(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Agent writes two files then list_files returns both names.

    Proves the LIST path against the same workspace/task scope that writes
    land in — the exact flow a multi-artifact tool (image + caption, etc.)
    will rely on.
    """
    _rustfs_env_defaults()
    from agentarea_common.artifacts import ArtifactService

    names = ["alpha.txt", "beta.txt"]

    agent_id = create_agent(
        alice_client,
        llm_model,
        name="file-list-agent",
        instruction=(
            "You have a file tool. Do EXACTLY this:\n"
            "  1. save_file to create the first file.\n"
            "  2. save_file to create the second file.\n"
            "  3. list_files with pattern '*'.\n"
            "  4. completion with {\"result\": <the list_files JSON you got>}."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={
            "description": (
                f"Create two files: {names[0]} with content 'A' and "
                f"{names[1]} with content 'B'. Then list all files."
            )
        },
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, agent_id, task_id, timeout=180.0)

    # Tool event for list_files must contain both names.
    list_events = [
        e for e in _tool_events(events, "ToolCallCompleted", "file")
        if (e["metadata"].get("arguments") or {}).get("action") == "list_files"
    ]
    assert list_events, "list_files never produced a ToolCallCompleted event"
    listing = str(list_events[-1]["metadata"].get("result") or "")
    for n in names:
        assert n in listing, (
            f"list_files result missing {n!r}; got {listing!r}"
        )

    # Storage layer cross-check: both objects present in RustFS.
    workspace_id = _psql(f"SELECT workspace_id FROM tasks WHERE id='{task_id}';")
    svc = ArtifactService()
    try:
        objs = asyncio.run(svc.list(workspace_id, prefix=f"tasks/{task_id}/"))
        paths = {o.path for o in objs}
        for n in names:
            expected = f"tasks/{task_id}/{n}"
            assert expected in paths, (
                f"expected artifact {expected} in RustFS; present: {sorted(paths)}"
            )
    finally:
        for n in names:
            try:
                asyncio.run(svc.delete(workspace_id, f"tasks/{task_id}/{n}"))
            except Exception:
                pass


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
