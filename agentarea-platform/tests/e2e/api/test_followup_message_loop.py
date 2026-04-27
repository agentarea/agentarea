"""Follow-up message loop end-to-end.

After the agent calls completion, the workflow does NOT terminate. It enters
``_awaiting_input`` and parks in ``workflow.wait_condition`` for up to 30 min,
listening for ``queue_message`` signals. Each follow-up message kicks off a
fresh iteration; each iteration ends with another ``WorkflowCompleted`` event
emitted from the same long-lived workflow.

This test locks that contract end-to-end against a real LLM:

  1. Start a chat task. Wait for ``WorkflowCompleted`` count == 1.
  2. POST ``queue_message`` via the control plane.
  3. Wait for ``WorkflowCompleted`` count == 2 — proves the wait_condition
     woke, a new iteration ran, and the agent completed again.
  4. Assert ``MessageQueued`` event landed and that turn 2 has its own
     ``LLMCallCompleted`` event (not just a replay of turn 1).
  5. Cancel to release the workflow (otherwise it parks for 30 min).

We also assert cross-workspace isolation on ``queue_message`` — Bob must
not be able to push a follow-up into Alice's task.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.e2e.api.conftest import create_agent


def _wait_for_event_count(
    client: httpx.Client,
    agent_id: str,
    task_id: str,
    event_type: str,
    expected: int,
    timeout: float = 90.0,
    poll: float = 1.0,
) -> list[dict]:
    """Poll /events until we see ``expected`` events of ``event_type``."""
    deadline = time.time() + timeout
    last: list[dict] = []
    last_count = 0
    while time.time() < deadline:
        resp = client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/events")
        resp.raise_for_status()
        last = resp.json()["events"]
        if any(
            e["event_type"] in ("WorkflowFailed", "TaskFailed", "LLMCallFailed")
            for e in last
        ):
            pytest.fail(
                f"task failed while waiting for {event_type}#{expected}: "
                f"{[e['event_type'] for e in last]}"
            )
        last_count = sum(1 for e in last if e["event_type"] == event_type)
        if last_count >= expected:
            return last
        time.sleep(poll)
    raise AssertionError(
        f"only saw {last_count} {event_type} events within {timeout}s, "
        f"expected {expected}; all events: {[e['event_type'] for e in last]}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_queue_message_resumes_completed_task(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """The full happy path: complete -> await -> queue_message -> complete again."""
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="followup-loop",
        instruction=(
            "You are a one-word responder. Reply with exactly one lowercase "
            "word and nothing else, then call the completion tool."
        ),
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Reply with the word: alpha"},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    # Turn 1 must complete.
    events = _wait_for_event_count(
        alice_client, agent_id, task_id, "WorkflowCompleted", 1, timeout=90.0
    )
    turn1_iterations = [e for e in events if e["event_type"] == "IterationCompleted"]
    assert turn1_iterations, "no IterationCompleted event from turn 1"

    # Send the follow-up. Endpoint must accept the command and the workflow
    # must still be addressable (not yet terminated).
    cmd = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "queue_message", "message": "Now reply with: beta"},
    )
    assert cmd.status_code == 200, cmd.text[:200]

    # Turn 2 must complete — count of WorkflowCompleted must reach 2.
    events = _wait_for_event_count(
        alice_client, agent_id, task_id, "WorkflowCompleted", 2, timeout=90.0
    )

    # MessageQueued event must have landed (proves the signal actually arrived
    # at the workflow, not just at the API layer).
    assert any(e["event_type"] == "MessageQueued" for e in events), (
        f"no MessageQueued event after queue_message: "
        f"{[e['event_type'] for e in events]}"
    )

    # Turn 2 must have run a real LLM call — not just replayed turn 1's events.
    llm_completed = [e for e in events if e["event_type"] == "LLMCallCompleted"]
    assert len(llm_completed) >= 2, (
        f"expected >=2 LLMCallCompleted events across both turns, got {len(llm_completed)}"
    )

    iteration_completed = [e for e in events if e["event_type"] == "IterationCompleted"]
    assert len(iteration_completed) >= 2, (
        f"expected >=2 IterationCompleted across both turns, got {len(iteration_completed)}"
    )

    # Release the workflow — otherwise it parks in awaiting_input for 30 min.
    cancel = alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")
    assert cancel.status_code in (200, 404), cancel.text[:200]


@pytest.mark.integration
def test_queue_message_cross_workspace_blocked(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_model: str,
) -> None:
    """Bob must not be able to push a follow-up into Alice's running task."""
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="followup-iso",
        instruction="Reply ok then complete.",
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Reply: ok"},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    bad = bob_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "queue_message", "message": "leak"},
    )
    assert bad.status_code == 404, (
        f"CRITICAL: Bob queued a message into Alice's task: HTTP {bad.status_code} "
        f"{bad.text[:200]!r}"
    )

    # Clean up — best effort, Alice's task may already have completed.
    alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")


@pytest.mark.integration
def test_queue_message_empty_text_rejected(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """The control plane must reject queue_message with no message field.

    The workflow handler also defends against empty text (logs a warning and
    drops the message), but the API contract should fail-fast at the edge.
    """
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="followup-empty",
        instruction="ok.",
    )
    task_id = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "ok"},
        timeout=30.0,
    ).raise_for_status().json()["id"]

    resp = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "queue_message"},
    )
    assert resp.status_code == 400, resp.text[:200]
    assert "message is required" in resp.json()["detail"].lower()

    alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")
