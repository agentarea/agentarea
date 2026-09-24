from __future__ import annotations

import time
import uuid

import httpx
import pytest

from tests.e2e.api.conftest import create_agent

A2A_HEADERS = {"A2A-Version": "1.0"}


def _a2a_rpc(
    client: httpx.Client,
    agent_id: str,
    method: str,
    params: dict,
    request_id: str | None = None,
) -> httpx.Response:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id or uuid.uuid4().hex[:8],
        "method": method,
        "params": params,
    }
    return client.post(
        f"/v1/agents/{agent_id}/a2a/rpc",
        json=payload,
        headers=A2A_HEADERS,
        timeout=30.0,
    )


def _message(text: str) -> dict:
    return {
        "message": {
            "messageId": uuid.uuid4().hex,
            "role": "ROLE_USER",
            "parts": [{"text": text}],
        }
    }


def _a2a_well_known(client: httpx.Client, agent_id: str) -> httpx.Response:
    return client.get(f"/v1/agents/{agent_id}/a2a/well-known", timeout=10.0)


def _extract_task_id(rpc_response: httpx.Response) -> str:
    assert rpc_response.status_code == 200, (
        f"RPC failed: {rpc_response.status_code} {rpc_response.text[:200]}"
    )
    body = rpc_response.json()
    assert body.get("error") is None, f"RPC error: {body.get('error')}"
    assert "result" in body, f"Missing result: {body}"
    task = body["result"]["task"]
    assert "id" in task, f"Missing task id: {task}"
    return task["id"]


def _poll_a2a_task(
    client: httpx.Client,
    agent_id: str,
    task_id: str,
    target_states: set[str],
    timeout: float = 90.0,
    poll: float = 1.0,
) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        resp = _a2a_rpc(client, agent_id, "GetTask", {"id": task_id})
        assert resp.status_code == 200, f"GetTask failed: {resp.text[:200]}"
        body = resp.json()
        assert body.get("error") is None, f"GetTask error: {body.get('error')}"
        last = body["result"]
        if last.get("status", {}).get("state") in target_states:
            return last
        time.sleep(poll)
    raise AssertionError(
        f"task {task_id} didn't reach {target_states} within {timeout}s; last={last}"
    )


@pytest.mark.integration
def test_a2a_well_known_returns_valid_agent_card(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-discover",
        instruction="Reply ok then complete.",
    )

    resp = _a2a_well_known(alice_client, agent_id)
    assert resp.status_code == 200, resp.text[:200]
    card = resp.json()

    assert card["name"] == "a2a-discover"
    rpc_url = card["supportedInterfaces"][0]["url"]
    assert rpc_url.endswith(f"/v1/agents/{agent_id}/a2a/rpc"), rpc_url
    assert card["capabilities"]["streaming"] is True


@pytest.mark.integration
def test_a2a_rpc_url_from_agent_card_is_reachable(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-url-reachable",
        instruction="Reply ok then complete.",
    )

    card = _a2a_well_known(alice_client, agent_id).raise_for_status().json()
    rpc_path = httpx.URL(card["supportedInterfaces"][0]["url"]).path

    resp = alice_client.post(
        rpc_path,
        json={
            "jsonrpc": "2.0",
            "id": "probe",
            "method": "GetExtendedAgentCard",
            "params": {},
        },
        headers=A2A_HEADERS,
        timeout=10.0,
    )
    assert resp.status_code == 200, (
        f"Agent card URL {rpc_path} returned {resp.status_code}: {resp.text[:200]}"
    )
    body = resp.json()
    assert body.get("error") is None, f"RPC error on agent card URL: {body}"


@pytest.mark.integration
@pytest.mark.slow
def test_a2a_tasks_send_creates_and_executes_task(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-task-send",
        instruction="Reply with exactly one lowercase word and nothing else.",
    )

    send_resp = _a2a_rpc(
        alice_client,
        agent_id,
        "SendMessage",
        _message("Reply with the word: omega"),
    )
    task_id = _extract_task_id(send_resp)

    task = _poll_a2a_task(
        alice_client,
        agent_id,
        task_id,
        {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED"},
        timeout=90.0,
    )
    assert task["status"]["state"] == "TASK_STATE_COMPLETED", (
        f"task failed: {task.get('status', {})}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_a2a_message_send_also_creates_task(alice_client: httpx.Client, llm_model: str) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-message-send",
        instruction="Reply with exactly one lowercase word and nothing else.",
    )

    send_resp = _a2a_rpc(
        alice_client,
        agent_id,
        "SendMessage",
        _message("Reply with the word: alpha"),
    )
    task_id = _extract_task_id(send_resp)

    task = _poll_a2a_task(
        alice_client,
        agent_id,
        task_id,
        {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED"},
        timeout=90.0,
    )
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.integration
@pytest.mark.slow
def test_a2a_tasks_cancel_terminates_running_task(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-cancel",
        instruction=(
            "You have a file tool. Create five files named step1.txt..step5.txt, "
            "writing a single line into each, one at a time. Do not batch. "
            "After all five, call completion."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )

    send_resp = _a2a_rpc(
        alice_client,
        agent_id,
        "SendMessage",
        _message("Create the five step files now."),
    )
    task_id = _extract_task_id(send_resp)

    time.sleep(1.0)

    cancel_resp = _a2a_rpc(alice_client, agent_id, "CancelTask", {"id": task_id})
    assert cancel_resp.status_code == 200, cancel_resp.text[:200]
    body = cancel_resp.json()
    assert body.get("error") is None, f"cancel error: {body.get('error')}"

    terminal = {"TASK_STATE_CANCELED", "TASK_STATE_FAILED", "TASK_STATE_COMPLETED"}
    task = _poll_a2a_task(alice_client, agent_id, task_id, terminal, timeout=30.0)
    assert task["status"]["state"] in terminal


@pytest.mark.integration
@pytest.mark.slow
def test_a2a_message_stream_returns_sse(alice_client: httpx.Client, llm_model: str) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-stream",
        instruction="Reply with exactly one lowercase word and nothing else.",
    )

    payload = {
        "jsonrpc": "2.0",
        "id": "stream-1",
        "method": "SendStreamingMessage",
        "params": _message("Reply with the word: stream"),
    }

    with alice_client.stream(
        "POST",
        f"/v1/agents/{agent_id}/a2a/rpc",
        json=payload,
        headers=A2A_HEADERS,
        timeout=120.0,
    ) as response:
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type, f"Expected SSE, got content-type={content_type}"


@pytest.mark.integration
def test_a2a_tasks_send_to_missing_agent_returns_error(
    alice_client: httpx.Client,
) -> None:
    fake_agent_id = str(uuid.uuid4())
    resp = _a2a_rpc(
        alice_client,
        fake_agent_id,
        "SendMessage",
        _message("Hello"),
    )
    assert resp.status_code == 404, (
        f"Expected 404 for missing agent, got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_a2a_invalid_method_returns_jsonrpc_error(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-invalid-method",
        instruction="ok.",
    )

    resp = _a2a_rpc(alice_client, agent_id, "invalid/method", {})
    assert resp.status_code in (200, 403), resp.text[:200]
    if resp.status_code == 200:
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == -32601


@pytest.mark.integration
def test_a2a_malformed_jsonrpc_returns_parse_error(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-parse-error",
        instruction="ok.",
    )

    resp = alice_client.post(
        f"/v1/agents/{agent_id}/a2a/rpc",
        content='{"jsonrpc": "2.0", "id": "x", "method": }',
        headers=A2A_HEADERS,
        timeout=10.0,
    )
    assert resp.status_code in (200, 403), resp.text[:200]
    if resp.status_code == 200:
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == -32700


@pytest.mark.integration
def test_a2a_tasks_get_cross_workspace_blocked(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_model: str,
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-iso",
        instruction="ok.",
    )

    send_resp = _a2a_rpc(
        alice_client,
        agent_id,
        "SendMessage",
        _message("ok"),
    )
    task_id = _extract_task_id(send_resp)

    cross = _a2a_rpc(bob_client, agent_id, "GetTask", {"id": task_id})
    if cross.status_code == 404:
        return
    assert cross.status_code == 200, cross.text[:200]
    body = cross.json()
    assert body.get("error") is not None, f"CRITICAL: Bob can read Alice's A2A task: {body}"
    assert body["error"]["code"] in (-32001, -32602)


@pytest.mark.integration
def test_a2a_well_known_is_public_or_protected(
    alice_client: httpx.Client, anon_client: httpx.Client, llm_model: str
) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="a2a-well-known-auth",
        instruction="ok.",
    )

    resp = _a2a_well_known(anon_client, agent_id)
    assert resp.status_code in (200, 401), (
        f"Unexpected status for anonymous well-known: {resp.status_code} {resp.text[:200]}"
    )
