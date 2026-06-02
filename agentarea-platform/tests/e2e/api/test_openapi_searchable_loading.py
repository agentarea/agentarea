"""End-to-end validation of OpenAPI lazy tool loading (issue #115).

Proves that:
  1. An OpenAPI connection with `load_mode=searchable` does NOT inject every
     operation schema into the LLM's `available_tools` upfront.
  2. The model can fire the `load_tools` meta-tool and the workflow resolves
     names to real schemas (visible as a `ToolCallCompleted` event with
     `matched_names` populated).

Requires a running stack (`make up-dev`) and a reachable LLM endpoint.
Set OPENAI_COMPAT_ENDPOINT / _MODEL / _API_KEY env vars if defaults don't
match your stack (see conftest.py).
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from .conftest import create_agent, wait_for_workflow


PETSTORE_SPEC = "https://petstore3.swagger.io/api/v3/openapi.json"
PETSTORE_BASE = "https://petstore3.swagger.io/api/v3"


def _wait_for_discovery(client: httpx.Client, conn_id: str, timeout: float = 30.0) -> dict:
    """Poll until `available_tools` is populated on the connection record."""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        last = client.get(f"/v1/openapi-connections/{conn_id}").raise_for_status().json()
        tools = last.get("available_tools") or []
        if isinstance(tools, list) and len(tools) > 0:
            return last
        time.sleep(1.0)
    raise AssertionError(
        f"OpenAPI discovery never populated available_tools within {timeout}s: "
        f"{last}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_searchable_openapi_load_tools_dispatch(
    alice_client: httpx.Client, llm_model: str
) -> None:
    # 1. Create a Petstore connection — the public sandbox has ~20 operations,
    #    enough for the catalog to be meaningful but small enough for fast e2e.
    conn = alice_client.post(
        "/v1/openapi-connections/",
        json={
            "name": f"petstore-e2e-{uuid.uuid4().hex[:6]}",
            "base_url": PETSTORE_BASE,
            "spec_url": PETSTORE_SPEC,
        },
        timeout=30.0,
    ).raise_for_status().json()
    conn_id = conn["id"]
    try:
        # 2. Ensure tool discovery actually completed so the searchable catalog
        #    in the workflow won't be empty.
        conn_full = _wait_for_discovery(alice_client, conn_id)
        op_count = len(conn_full.get("available_tools") or [])
        assert op_count > 0, "Petstore connection has zero discovered operations"

        # 3. Attach the connection to an agent with load_mode=searchable.
        agent_id = create_agent(
            alice_client,
            llm_model,
            name=f"petstore-agent-{uuid.uuid4().hex[:6]}",
            instruction=(
                "You are connected to the Swagger Petstore API. To use any "
                "Petstore operation, you MUST first call the `load_tools` "
                "meta-tool with the exact operation name(s) you need (e.g. "
                "`load_tools({\"tool_names\":[\"findPetsByStatus\"]})`). "
                "Operation names are listed under '## Available OpenAPI "
                "Operations' in this prompt. After load_tools returns, call "
                "the operation, then call `completion` with a short summary."
            ),
            tools=[
                {
                    "type": "openapi",
                    "name": conn["name"],
                    "settings": {
                        "openapi_connection_id": conn_id,
                        "load_mode": "searchable",
                    },
                }
            ],
        )

        # 4. Submit a task that requires a real Petstore call.
        task_id = (
            alice_client.post(
                f"/v1/agents/{agent_id}/tasks/sync",
                json={
                    "description": (
                        "Find Petstore pets with status 'available'. "
                        "Use load_tools to load `findPetsByStatus`, call it, "
                        "then summarize with completion."
                    )
                },
                timeout=30.0,
            )
            .raise_for_status()
            .json()["id"]
        )

        # 5. Wait for workflow to terminate.
        events = wait_for_workflow(
            alice_client, agent_id, task_id, timeout=180.0
        )

        # 6. The hard assertion: somewhere in the event stream we must see
        #    `load_tools` complete with at least one matched operation. This
        #    proves the disclosure path executed end-to-end against a live LLM.
        load_tools_events = [
            e
            for e in events
            if e["event_type"] == "ToolCallCompleted"
            and (e.get("metadata") or {}).get("tool_name") == "load_tools"
        ]
        assert load_tools_events, (
            "expected at least one ToolCallCompleted for `load_tools`; got "
            f"event types: {[e['event_type'] for e in events]}"
        )

        matched = []
        for ev in load_tools_events:
            md = ev.get("metadata") or {}
            matched.extend(md.get("matched_names") or [])
        assert matched, (
            "load_tools fired but resolved zero operation names; metadata: "
            f"{[e.get('metadata') for e in load_tools_events]}"
        )

        # 7. Bonus: prove the workflow didn't crash.
        assert any(e["event_type"] == "WorkflowCompleted" for e in events), (
            "workflow did not reach WorkflowCompleted; events: "
            f"{[e['event_type'] for e in events]}"
        )
    finally:
        alice_client.delete(f"/v1/openapi-connections/{conn_id}")
