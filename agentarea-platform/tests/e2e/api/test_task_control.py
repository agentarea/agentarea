"""Task control-plane HTTP API end-to-end.

These endpoints send signals into a running Temporal workflow:

  POST   /v1/agents/{a}/tasks/{t}/pause
  POST   /v1/agents/{a}/tasks/{t}/resume
  POST   /v1/agents/{a}/tasks/{t}/command         (queue_message, update_budget, ...)
  POST   /v1/agents/{a}/tasks/{t}/resolve-escalation
  DELETE /v1/agents/{a}/tasks/{t}                 (cancel)

Coverage strategy:

  * Contract paths are deterministic (404 / 400 for bad state, missing
    fields, cross-workspace) — assert them straight.
  * Happy-path pause/resume races against task completion; we use a
    multi-step file-tool task to keep the workflow busy for ~10s and
    accept either ``200`` (signal landed) or ``400`` (workflow already
    completed) as a non-failure outcome, and assert the *contract*: the
    API never silently 500s, and the final task state is reachable.
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from tests.e2e.api.conftest import create_agent, wait_for_workflow


def _start_chat_task(
    client: httpx.Client, llm_model: str, *, agent_name: str, prompt: str
) -> tuple[str, str]:
    agent_id = create_agent(
        client,
        llm_model,
        name=agent_name,
        instruction="Reply with exactly one lowercase word and nothing else.",
    )
    task_id = client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": prompt},
        timeout=30.0,
    ).raise_for_status().json()["id"]
    return agent_id, task_id


def _wait_for_status(
    client: httpx.Client,
    agent_id: str,
    task_id: str,
    target: set[str],
    timeout: float = 60.0,
    poll: float = 0.5,
) -> str:
    """Poll /status until Temporal-level status is in ``target``.

    Events fire slightly before Temporal external status flips (the
    workflow result still has to flush). For state-gated pause/resume
    tests we must wait for status, not events.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        resp = client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/status")
        resp.raise_for_status()
        last = (resp.json().get("status") or "").lower()
        if last in target:
            return last
        time.sleep(poll)
    raise AssertionError(
        f"task didn't reach any of {target} within {timeout}s; last={last!r}"
    )


def _start_long_file_task(
    client: httpx.Client, llm_model: str, *, agent_name: str
) -> tuple[str, str]:
    """A task with enough tool calls that we have a window to signal it."""
    agent_id = create_agent(
        client,
        llm_model,
        name=agent_name,
        instruction=(
            "You have a file tool. Create five files named step1.txt..step5.txt, "
            "writing a single line into each, one at a time. Do not batch. "
            "After all five, call completion."
        ),
        tools=[{"type": "code", "name": "agentarea/files"}],
    )
    task_id = client.post(
        f"/v1/agents/{agent_id}/tasks/sync",
        json={"description": "Create the five step files now."},
        timeout=30.0,
    ).raise_for_status().json()["id"]
    return agent_id, task_id


@pytest.mark.integration
def test_pause_unknown_task_returns_404(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id, _ = _start_chat_task(
        alice_client, llm_model, agent_name="ctrl-404", prompt="ok"
    )
    fake_task_id = uuid.uuid4()
    resp = alice_client.post(f"/v1/agents/{agent_id}/tasks/{fake_task_id}/pause")
    assert resp.status_code == 404, resp.text[:200]


@pytest.mark.integration
def test_resume_unknown_task_returns_404(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id, _ = _start_chat_task(
        alice_client, llm_model, agent_name="ctrl-resume-404", prompt="ok"
    )
    fake_task_id = uuid.uuid4()
    resp = alice_client.post(f"/v1/agents/{agent_id}/tasks/{fake_task_id}/resume")
    assert resp.status_code == 404, resp.text[:200]


@pytest.mark.integration
@pytest.mark.slow
def test_pause_resume_terminal_task_returns_400(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Pause and resume both reject terminal states.

    ``AgentExecutionWorkflow`` is a long-lived chat session — it stays in
    Temporal's "running" state for 30 minutes after the user-visible
    "task completed" log fires. So we drive it to a terminal Temporal
    state via cancel, then assert the validation contract.
    """
    agent_id, task_id = _start_long_file_task(
        alice_client, llm_model, agent_name="ctrl-terminal"
    )
    # Let the workflow register so cancel signals it.
    time.sleep(1.0)
    cancel = alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")
    assert cancel.status_code in (200, 404), cancel.text[:200]
    if cancel.status_code == 404:
        pytest.skip("workflow finished before we could cancel it")

    _wait_for_status(
        alice_client, agent_id, task_id,
        target={"cancelled", "failed", "completed"}, timeout=60.0,
    )

    pause = alice_client.post(f"/v1/agents/{agent_id}/tasks/{task_id}/pause")
    assert pause.status_code == 400, pause.text[:200]
    assert "cannot pause" in pause.json()["detail"].lower()

    resume = alice_client.post(f"/v1/agents/{agent_id}/tasks/{task_id}/resume")
    assert resume.status_code == 400, resume.text[:200]
    assert "cannot resume" in resume.json()["detail"].lower()


@pytest.mark.integration
def test_command_unknown_returns_400(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id, task_id = _start_chat_task(
        alice_client, llm_model, agent_name="ctrl-cmd-bad", prompt="ok"
    )
    resp = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "make_tea"},
    )
    assert resp.status_code == 400, resp.text[:200]
    assert "unknown command" in resp.json()["detail"].lower()


@pytest.mark.integration
def test_command_change_model_requires_model_id(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id, task_id = _start_chat_task(
        alice_client, llm_model, agent_name="ctrl-cmd-validate", prompt="ok"
    )
    resp = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "change_model"},
    )
    assert resp.status_code == 400, resp.text[:200]
    assert "model_instance_id" in resp.json()["detail"]


@pytest.mark.integration
def test_command_queue_message_requires_message(
    alice_client: httpx.Client, llm_model: str
) -> None:
    agent_id, task_id = _start_chat_task(
        alice_client, llm_model, agent_name="ctrl-cmd-msg", prompt="ok"
    )
    resp = alice_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "queue_message"},
    )
    assert resp.status_code == 400, resp.text[:200]
    assert "message is required" in resp.json()["detail"].lower()


@pytest.mark.integration
def test_pause_resume_cross_workspace_blocked(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_model: str,
) -> None:
    """Bob must not be able to signal Alice's running workflow."""
    agent_id, task_id = _start_chat_task(
        alice_client,
        llm_model,
        agent_name="ctrl-cross-ws",
        prompt="Reply with the word: ok",
    )
    pause = bob_client.post(f"/v1/agents/{agent_id}/tasks/{task_id}/pause")
    assert pause.status_code == 404, (
        f"CRITICAL: Bob paused Alice's task: HTTP {pause.status_code} "
        f"{pause.text[:200]!r}"
    )
    resume = bob_client.post(f"/v1/agents/{agent_id}/tasks/{task_id}/resume")
    assert resume.status_code == 404, resume.text[:200]
    cancel = bob_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")
    assert cancel.status_code == 404, cancel.text[:200]
    cmd = bob_client.post(
        f"/v1/agents/{agent_id}/tasks/{task_id}/command",
        json={"command": "update_budget", "budget_usd": 1.0},
    )
    assert cmd.status_code == 404, cmd.text[:200]


@pytest.mark.integration
@pytest.mark.slow
def test_cancel_running_task_terminates_workflow(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """DELETE on a live task either cancels it or 404s if already done."""
    agent_id, task_id = _start_long_file_task(
        alice_client, llm_model, agent_name="ctrl-cancel"
    )
    # Give the workflow a beat to register so cancel signal lands on it.
    time.sleep(1.0)

    resp = alice_client.delete(f"/v1/agents/{agent_id}/tasks/{task_id}")
    # 200 = signal landed; 404 = already done before we got there.
    assert resp.status_code in (200, 404), resp.text[:200]

    if resp.status_code == 200:
        # The workflow event stream goes silent after a cancel signal —
        # protocol events stop firing — so we poll Temporal-level status
        # instead. "cancelled" is the goal; "completed"/"failed" also
        # acceptable if the workflow raced past us.
        _wait_for_status(
            alice_client, agent_id, task_id,
            target={"cancelled", "failed", "completed"}, timeout=60.0,
        )


@pytest.mark.integration
@pytest.mark.slow
def test_pause_resume_running_task_signals_workflow(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Best-effort pause/resume on a multi-step task.

    The task is instructed to make ~5 sequential tool calls, giving us a
    window of seconds in which the workflow is alive. We accept that the
    workflow may have completed before our signal arrives — that's a
    timing artifact, not a regression. What we never accept:

      * 500 from the signal endpoint
      * pause returning 200 but resume returning 500
      * the task never reaching a terminal state afterwards
    """
    agent_id, task_id = _start_long_file_task(
        alice_client, llm_model, agent_name="ctrl-pause-resume"
    )
    # Try to land the pause while the workflow is still doing tool calls.
    pause = alice_client.post(f"/v1/agents/{agent_id}/tasks/{task_id}/pause")
    assert pause.status_code in (200, 400), pause.text[:200]

    if pause.status_code == 200:
        # Resume must succeed since we just paused.
        resume = alice_client.post(
            f"/v1/agents/{agent_id}/tasks/{task_id}/resume"
        )
        assert resume.status_code == 200, resume.text[:200]

    # Either way, the workflow must terminate cleanly.
    events = wait_for_workflow(
        alice_client, agent_id, task_id, timeout=180.0
    )
    types = [e["event_type"] for e in events]
    assert any(
        t in types for t in ("WorkflowCompleted", "WorkflowFailed")
    ), types
