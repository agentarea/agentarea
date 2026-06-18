"""End-to-end agent delegation against a real LLM.

The platform implements ``delegate_to_<agent>`` tools as Temporal child
workflows (``agent_execution_workflow.py:_execute_agent_delegation``) with
``ParentClosePolicy.TERMINATE``. The coordinator awaits children via
``asyncio.gather``.

The bug this test guards against: a delegated child workflow used to enter
the 30-minute ``_await_follow_up`` state after calling completion, exactly
like a top-level user task. The parent's ``execute_child_workflow`` then
blocked until ``DELEGATION_TIMEOUT`` (10 min) cancelled the children. The
coordinator never finished.

A delegated child has no end-user on the other end of its conversation, so
follow-ups make no sense — it must terminate after first completion so the
parent can pick up the result. This test enforces that:

  coordinator + 1 specialist child must complete within 90 s.

Without the fix this test fails after ~10 min via DELEGATION_TIMEOUT.
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.e2e.api.conftest import create_agent, wait_for_workflow

ALLOW_ALL_TOOLS_TASK_POLICY = {"tools": {"allowed": ["*"]}}


@pytest.mark.integration
@pytest.mark.slow
def test_coordinator_with_one_child_completes(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """Regression: delegated children must NOT enter await_input.

    Without the fix, this hangs for 10 minutes (DELEGATION_TIMEOUT) and
    fails. With the fix, it completes in seconds — the child terminates on
    completion, the parent's execute_child_workflow returns immediately.
    """
    specialist_id = create_agent(
        alice_client,
        llm_model,
        name=f"speller-{int(time.time())}",
        instruction=(
            "Reply with the single lowercase word the user asks you to spell, "
            "then call completion."
        ),
    )

    specialist = alice_client.get(f"/v1/agents/{specialist_id}").raise_for_status().json()
    specialist_name = specialist["name"]

    coord_id = create_agent(
        alice_client,
        llm_model,
        name=f"coord-{int(time.time())}",
        instruction=(
            f"You have a single tool: delegate_to_{specialist_name.replace('-','_')}. "
            "Call it exactly once with the message the user gave you. "
            "When it returns, call completion with one short sentence quoting the "
            "specialist's reply."
        ),
        tools=[{"type": "agent", "name": specialist_name}],
    )

    task_id = alice_client.post(
        f"/v1/agents/{coord_id}/tasks/sync",
        json={
            "description": f"Ask {specialist_name} to spell the word: omega",
            "task_policy": ALLOW_ALL_TOOLS_TASK_POLICY,
        },
        timeout=30.0,
    ).raise_for_status().json()["id"]

    # Coordinator is a top-level task — it stays in await_input after
    # completion (correct behavior for top-level tasks). So we don't wait
    # for terminal *status*; we wait for the event that proves the agent
    # loop reached completion. If the delegation bug regresses, the
    # coordinator's child sits in await_input for 10 min until
    # DELEGATION_TIMEOUT cancels it — WorkflowCompleted never fires.
    events = wait_for_workflow(alice_client, coord_id, task_id, timeout=90.0)
    types = [e["event_type"] for e in events]
    assert "AgentDelegationStarted" in types, types
    assert "AgentDelegationCompleted" in types, types
    assert "WorkflowCompleted" in types, types

    # Release the coordinator's 30-min await window.
    alice_client.delete(f"/v1/agents/{coord_id}/tasks/{task_id}")
