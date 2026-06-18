"""Task-artifact HTTP API end-to-end.

The backend stores agent-produced files in RustFS under
``workspaces/{workspace_id}/tasks/{task_id}/``. These tests prove the
HTTP surface the frontend and external clients rely on:

  GET /v1/agents/{agent_id}/tasks/{task_id}/artifacts
    -> list of {path, size, content_type, last_modified, download_url}

  (download is via an authenticated API URL on the item.)

Tests drive a real agent, it writes files via ``agentarea/files``, then
we hit the list endpoint and follow the download URL to verify the
bytes match. Cross-workspace access returns an empty list (never leaks
another workspace's artifacts) — that's the load-bearing invariant.
"""

from __future__ import annotations

import httpx
import pytest

from tests.e2e.api.conftest import create_agent, wait_for_workflow

ALLOW_ALL_TOOLS_TASK_POLICY = {"tools": {"allowed": ["*"]}}


def _run_file_task(
    client: httpx.Client, llm_model: str, description: str, agent_name: str
) -> str:
    agent_id = create_agent(
        client,
        llm_model,
        name=agent_name,
        instruction=(
            "You have a file tool. Use save_file once per requested file, "
            "then call completion."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={
            "description": description,
            "task_policy": ALLOW_ALL_TOOLS_TASK_POLICY,
        },
        timeout=30.0,
    ).raise_for_status().json()["id"]
    wait_for_workflow(client, agent_id, task_id, timeout=180.0)
    return f"{agent_id}::{task_id}"


@pytest.mark.integration
@pytest.mark.slow
def test_list_task_artifacts_endpoint(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Agent writes a file; the artifacts endpoint lists it with a download URL."""
    file_name = "report.txt"
    body = "final-report-delta-9"

    ids = _run_file_task(
        alice_client,
        llm_model,
        description=(
            f"Create file {file_name} with exact content: {body}. "
            "Do not create any other files."
        ),
        agent_name="art-list-agent",
    )
    agent_id, task_id = ids.split("::")

    resp = alice_client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/artifacts")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert isinstance(items, list)

    matched = [i for i in items if i["path"].endswith(file_name)]
    assert matched, f"no artifact ending in {file_name!r}; got {items!r}"
    item = matched[0]
    assert item["size"] > 0
    assert item["content_type"]
    assert item["download_url"].startswith("/v1/")

    # Download URL must serve the actual bytes with the caller's auth.
    bytes_resp = alice_client.get(item["download_url"])
    bytes_resp.raise_for_status()
    assert body in bytes_resp.text, (
        f"download URL served wrong bytes; expected {body!r} in {bytes_resp.text!r}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_task_artifacts_are_workspace_scoped(
    alice_client: httpx.Client, bob_client: httpx.Client, llm_model: str
) -> None:
    """Bob must never see Alice's task artifacts via the list endpoint."""
    ids = _run_file_task(
        alice_client,
        llm_model,
        description="Create file alice-only.txt with exact content: alice-only-body.",
        agent_name="alice-art-agent",
    )
    agent_id, task_id = ids.split("::")

    # Bob asks for Alice's task's artifacts → 404 (task isn't in his workspace).
    cross = bob_client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/artifacts")
    assert cross.status_code in (403, 404), (
        f"CRITICAL: Bob accessed Alice's artifacts: HTTP {cross.status_code} "
        f"{cross.text!r}"
    )
