"""Task orchestration E2E: skills, delegation, files, and MCP tools."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator

import httpx
import pytest

from tests.e2e.api.conftest import create_agent, wait_for_workflow

SKILL_MARKER = "SKILL_MARKER_E2E_7F3A"
CONTEXT7_MARKER = "CTX7_E2E_DOCS_READY"
OPEN_MCP_MARKER = "OPEN_MCP_ECHO_READY"


def _ensure_artifacts_bucket() -> None:
    """Ensure the local RustFS artifacts bucket exists for file-tool writes."""
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "rustfsadmin"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "rustfsadmin"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        endpoint_url=os.environ.get("PUBLIC_S3_ENDPOINT", "http://localhost:9000"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    bucket = os.environ.get("ARTIFACTS_BUCKET_NAME", "artifacts")
    for attempt in range(3):
        try:
            client.head_bucket(Bucket=bucket)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise

        try:
            client.create_bucket(Bucket=bucket)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                return
            message = e.response.get("Error", {}).get("Message", str(e))
            if code == "InternalError" and "Storage resources are insufficient" in message:
                pytest.skip(f"Local RustFS cannot create artifact bucket {bucket!r}: {message}")
            if attempt == 2:
                raise
            time.sleep(0.5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"local MCP fixture did not open port {port}")


@pytest.fixture
def local_context7_mcp_server() -> Iterator[str]:
    """Run a deterministic streamable-http MCP fixture on the host.

    The backend container reaches the host via host.docker.internal on macOS.
    Override E2E_MCP_HOST_FOR_BACKEND for Linux or non-Docker backends.
    """
    port = _free_port()
    code = textwrap.dedent(
        f"""
        from fastmcp import FastMCP

        mcp = FastMCP(name="e2e-context7-open")

        @mcp.tool
        async def context7_lookup(library: str, topic: str) -> str:
            return "{CONTEXT7_MARKER}: " + library + " / " + topic

        @mcp.tool
        async def open_echo(text: str) -> str:
            return "{OPEN_MCP_MARKER}: " + text

        if __name__ == "__main__":
            mcp.run(transport="streamable-http", host="0.0.0.0", port={port})
        """
    )
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(port)
        backend_host = os.environ.get("E2E_MCP_HOST_FOR_BACKEND", "host.docker.internal")
        yield f"http://{backend_host}:{port}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _create_skill(client: httpx.Client, *, name: str, description: str, content: str) -> str:
    resp = client.post(
        "/v1/skills",
        json={"name": name, "description": description, "content": content},
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _create_agent_with_skills(
    client: httpx.Client,
    model_id: str,
    *,
    name: str,
    instruction: str,
    tools: list[dict] | None = None,
    skill_ids: list[str] | None = None,
) -> str:
    body: dict = {
        "name": name,
        "description": "task orchestration e2e",
        "instruction": instruction,
        "model_id": model_id,
        "agent_type": "chat",
    }
    if tools:
        body["tools"] = tools
    if skill_ids:
        body["skill_ids"] = skill_ids

    return client.post("/v1/agents/", json=body).raise_for_status().json()["id"]


def _tool_events(events: list[dict], tool_name: str) -> list[dict]:
    return [
        event
        for event in events
        if event["event_type"] == "ToolCallCompleted"
        and event.get("metadata", {}).get("tool_name") == tool_name
    ]


def _create_mcp_instance(client: httpx.Client, *, name: str, endpoint_url: str) -> str:
    resp = client.post(
        "/v1/mcp-server-instances/",
        json={
            "name": name,
            "description": "deterministic e2e MCP fixture",
            "json_spec": {"type": "url", "endpoint_url": endpoint_url},
        },
        timeout=70.0,
    )
    if resp.status_code >= 400:
        pytest.skip(
            f"Could not create local MCP fixture instance: {resp.status_code} {resp.text[:300]}"
        )
    body = resp.json()
    verification = body.get("verification") or {}
    if verification.get("status") != "succeeded":
        pytest.skip(f"Local MCP fixture did not verify: {verification}")
    tools = client.get(
        "/v1/agents/tools",
        params={"include": "mcp", "mcp_instance_id": body["id"]},
    ).raise_for_status().json()
    tool_names = {tool["name"] for tool in tools}
    assert {"context7_lookup", "open_echo"} <= tool_names
    return body["id"]


@pytest.mark.integration
@pytest.mark.slow
def test_orchestrator_delegates_to_skill_file_agent_and_mcp_agent(
    alice_client: httpx.Client,
    llm_model: str,
    local_context7_mcp_server: str,
) -> None:
    _ensure_artifacts_bucket()
    suffix = int(time.time())

    scribe_skill_id = _create_skill(
        alice_client,
        name=f"scribe-skill-{suffix}",
        description="Writes the required E2E skill token into task artifacts.",
        content=(
            "---\n"
            f"name: scribe-skill-{suffix}\n"
            "description: E2E file-writing protocol\n"
            "---\n"
            f"When activated, every file you write MUST include the exact marker {SKILL_MARKER}.\n"
            "Use the file tool to persist the requested artifact before completing.\n"
        ),
    )
    orch_skill_id = _create_skill(
        alice_client,
        name=f"orchestration-skill-{suffix}",
        description="Forces the coordinator to delegate to both specialists.",
        content=(
            "---\n"
            f"name: orchestration-skill-{suffix}\n"
            "description: E2E coordinator protocol\n"
            "---\n"
            "When activated, delegate to every specialist exactly once before completing.\n"
        ),
    )

    mcp_instance_id = _create_mcp_instance(
        alice_client,
        name=f"context7-open-{suffix}",
        endpoint_url=local_context7_mcp_server,
    )

    scribe_id = _create_agent_with_skills(
        alice_client,
        llm_model,
        name=f"skill-scribe-{suffix}",
        instruction=(
            f"First call activate_skill with skill_name='scribe-skill-{suffix}'. "
            "Then create skill-report.txt with save_file. The file content must include "
            f"the exact marker {SKILL_MARKER}. Then call completion with the filename."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
        skill_ids=[scribe_skill_id],
    )
    mcp_id = create_agent(
        alice_client,
        llm_model,
        name=f"mcp-specialist-{suffix}",
        instruction=(
            "Call context7_lookup with library='pytest' and topic='fixtures'. "
            "Then call open_echo with text='delegation-mcp-check'. "
            "Then call completion with both tool results."
        ),
        tools=[
            {
                "type": "mcp",
                "name": mcp_instance_id,
                "settings": {"allowed_tools": ["context7_lookup", "open_echo"]},
            }
        ],
    )

    scribe = alice_client.get(f"/v1/agents/{scribe_id}").raise_for_status().json()
    mcp_agent = alice_client.get(f"/v1/agents/{mcp_id}").raise_for_status().json()

    coord_id = _create_agent_with_skills(
        alice_client,
        llm_model,
        name=f"main-orchestrator-{suffix}",
        instruction=(
            f"First call activate_skill with skill_name='orchestration-skill-{suffix}'. "
            f"Then call delegate_to_{scribe['name'].replace('-', '_')} once and ask it "
            "to create skill-report.txt. Also call "
            f"delegate_to_{mcp_agent['name'].replace('-', '_')} once and ask it to run "
            "the Context7 lookup and open echo MCP checks. After both return, call "
            "completion with one concise summary."
        ),
        tools=[
            {"type": "agent", "name": scribe["name"]},
            {"type": "agent", "name": mcp_agent["name"]},
        ],
        skill_ids=[orch_skill_id],
    )

    task_id = alice_client.post(
        f"/v1/agents/{coord_id}/tasks/sync",
        json={"description": "Run the skill/file specialist and the MCP specialist."},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    events = wait_for_workflow(alice_client, coord_id, task_id, timeout=180.0)
    assert _tool_events(events, "activate_skill"), "coordinator did not activate its skill"

    completed = [e for e in events if e["event_type"] == "AgentDelegationCompleted"]
    assert len(completed) == 2, [e["event_type"] for e in events]
    assert all(e["metadata"].get("success") is True for e in completed), [
        e["metadata"] for e in completed
    ]

    by_agent = {e["metadata"]["target_agent_name"]: e["metadata"] for e in completed}

    scribe_meta = by_agent[scribe["name"]]
    scribe_events = alice_client.get(
        f"/v1/agents/{scribe_meta['target_agent_id']}/tasks/"
        f"{scribe_meta['child_task_id']}/events"
    ).raise_for_status().json()["events"]
    assert _tool_events(scribe_events, "activate_skill"), "scribe did not activate its skill"

    artifacts = alice_client.get(
        f"/v1/agents/{scribe_meta['target_agent_id']}/tasks/"
        f"{scribe_meta['child_task_id']}/artifacts"
    ).raise_for_status().json()
    report = next((a for a in artifacts if a["path"].endswith("skill-report.txt")), None)
    assert report, f"skill-report.txt missing; got {[a['path'] for a in artifacts]}"
    report_body = httpx.get(report["download_url"], timeout=10.0).text
    assert SKILL_MARKER in report_body

    mcp_meta = by_agent[mcp_agent["name"]]
    mcp_events = alice_client.get(
        f"/v1/agents/{mcp_meta['target_agent_id']}/tasks/"
        f"{mcp_meta['child_task_id']}/events"
    ).raise_for_status().json()["events"]
    context7_events = _tool_events(mcp_events, "context7_lookup")
    open_echo_events = _tool_events(mcp_events, "open_echo")
    assert context7_events, [e["metadata"] for e in mcp_events if e["event_type"] == "ToolCallCompleted"]
    assert open_echo_events, [e["metadata"] for e in mcp_events if e["event_type"] == "ToolCallCompleted"]
    assert CONTEXT7_MARKER in str(context7_events[-1]["metadata"].get("result") or "")
    assert OPEN_MCP_MARKER in str(open_echo_events[-1]["metadata"].get("result") or "")

    alice_client.delete(f"/v1/agents/{coord_id}/tasks/{task_id}")
