"""Agent-driven trigger creation against a real LLM endpoint.

Proves the agent can take a natural-language scheduling request from the user
("every weekday morning summarize my inbox", "remind me tomorrow to call Bob")
and turn it into a real cron trigger row via the ``agentarea/triggers``
platform tool.

Like the other live e2e tests in this directory, we drive a real OpenAI-
compatible LLM (configured via ``OPENAI_COMPAT_*`` env vars in conftest) and
poll the workflow's events for the tool call. We then go straight to the
``triggers`` table to confirm the row really landed — the tool's success
string is not enough.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.e2e.api.conftest import _psql, create_agent, wait_for_workflow

ALLOW_ALL_TOOLS_TASK_POLICY = {"tools": {"allowed": ["*"]}}


def _trigger_create_calls(events: list[dict]) -> list[dict]:
    """Return every successful create_cron call the agent made.

    The platform exposes the toolset under tool_name="triggers" with a
    multi-method dispatch shape (``action`` + ``<action>_<param>`` arg keys).
    """
    calls: list[dict] = []
    for ev in events:
        if ev["event_type"] != "ToolCallCompleted":
            continue
        md = ev.get("metadata", {})
        if md.get("tool_name") != "triggers":
            continue
        args = md.get("arguments") or {}
        if args.get("action") != "create_cron":
            continue
        result = md.get("result")
        if not result or str(result).startswith("Error"):
            continue
        try:
            payload = json.loads(result) if isinstance(result, str) else result
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("trigger_type") == "cron":
            calls.append({"args": args, "result": payload})
    return calls


def _agent_with_triggers(client: httpx.Client, llm_model: str, *, name: str) -> str:
    """Create an agent that has the triggers toolset and a strict scheduling instruction."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return create_agent(
        client,
        llm_model,
        name=name,
        instruction=(
            "You are a scheduling assistant. When the user asks for a recurring or "
            "future task, you MUST call the `triggers` tool's `create_cron` action "
            "exactly once with these arguments:\n"
            "  - name: a short human-readable label\n"
            "  - cron_expression: a 5-field cron expression in UTC\n"
            "  - description: brief context\n"
            "  - timezone: 'UTC'\n"
            "Do NOT pass agent_id — the tool defaults it to you.\n"
            f"Today's date is {today} (UTC). Convert relative phrases like "
            "'tomorrow at 9am' or 'every weekday morning' to a precise UTC cron "
            "expression. After the trigger is created, call `completion` with "
            "{\"result\": <the trigger id you got back>}. Do not call any other "
            "tools. Do not invent additional steps."
        ),
        tools=[{"type": "code", "name": "agentarea/triggers"}],
    )


def _self_agent_id_in_db(task_id: str) -> str:
    """The agent_id of the agent that ran this task — used to fix up the agent's
    placeholder ``__SELF__`` arg if needed for assertions on the DB row."""
    return _psql(f"SELECT agent_id FROM tasks WHERE id='{task_id}';")


def _cron_rows_for_agent(agent_id: str) -> list[dict]:
    """Read the trigger rows the agent created. Bypasses API auth so the test
    sees what really landed in the table, not what the API filters back."""
    raw = _psql(
        "SELECT id, name, cron_expression, timezone, trigger_type, is_active "
        f"FROM triggers WHERE agent_id='{agent_id}' AND trigger_type='cron' "
        "ORDER BY created_at DESC;"
    )
    rows: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        cols = line.split("|")
        if len(cols) < 6:
            continue
        rows.append(
            {
                "id": cols[0],
                "name": cols[1],
                "cron_expression": cols[2],
                "timezone": cols[3],
                "trigger_type": cols[4],
                "is_active": cols[5] in ("t", "true", "1"),
            }
        )
    return rows


def _drive_scheduling_task(
    client: httpx.Client, llm_model: str, agent_name: str, user_message: str
) -> tuple[str, str, list[dict]]:
    """Create the agent, send one user message, wait for workflow completion.

    Returns (agent_id, task_id, events).
    """
    agent_id = _agent_with_triggers(client, llm_model, name=agent_name)
    task_id = (
        client.post(
            f"/v1/agents/{agent_id}/tasks/sync",
            json={
                "description": user_message,
                "task_policy": ALLOW_ALL_TOOLS_TASK_POLICY,
            },
            timeout=60.0,
        )
        .raise_for_status()
        .json()["id"]
    )
    events = wait_for_workflow(client, agent_id, task_id, timeout=180.0)
    return agent_id, task_id, events


@pytest.mark.integration
@pytest.mark.slow
def test_agent_creates_recurring_cron_for_weekday_morning_request(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """'Every weekday at 9am UTC summarize my inbox' -> cron trigger row exists.

    We do not lock down the exact cron string the model picks (LLM phrasing is
    fuzzy) — we only require that:
      - some create_cron call succeeded,
      - the row landed in the triggers table for this agent,
      - the cron expression has hour=9 and a weekday-restricted day-of-week,
      - the trigger is active.
    """
    agent_id, task_id, events = _drive_scheduling_task(
        alice_client,
        llm_model,
        agent_name="sched-weekday",
        user_message=(
            "Every weekday at 9am UTC, please summarize my inbox. "
            "Schedule it now."
        ),
    )

    workflow_event_types = [e["event_type"] for e in events]
    assert "WorkflowCompleted" in workflow_event_types, (
        f"workflow did not finish cleanly; events: {workflow_event_types}"
    )

    calls = _trigger_create_calls(events)
    assert calls, (
        "agent never produced a successful triggers.create_cron call; "
        f"events seen: {workflow_event_types}"
    )

    rows = _cron_rows_for_agent(agent_id)
    assert rows, f"no cron rows landed in triggers table for agent {agent_id}"
    row = rows[0]
    assert row["is_active"], f"cron trigger created but inactive: {row}"

    cron = row["cron_expression"]
    parts = cron.split()
    assert len(parts) in (5, 6), f"unexpected cron field count: {cron!r}"
    minute, hour, _dom, _month, dow = parts[:5]
    assert hour == "9", f"expected 9am hour, got cron {cron!r}"
    assert minute in ("0", "00"), f"expected zero minute, got cron {cron!r}"
    assert dow not in ("*", "?"), (
        f"expected weekday-restricted day-of-week, got cron {cron!r}"
    )


@pytest.mark.integration
@pytest.mark.slow
def test_agent_creates_one_shot_cron_for_tomorrow_reminder(
    alice_client: httpx.Client, llm_model: str
) -> None:
    """'Remind me tomorrow at 9am to call Bob' -> cron pinned to tomorrow's date.

    There's no SCHEDULED trigger type yet, so the cleanest way to express
    a one-shot reminder is a cron with a specific day-of-month + month.
    We assert the cron's day-of-month matches tomorrow (UTC) and the hour
    matches the requested time, which is the strongest evidence the model
    actually understood "tomorrow" and didn't just schedule a daily 9am.
    """
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()

    agent_id, _task_id, events = _drive_scheduling_task(
        alice_client,
        llm_model,
        agent_name="sched-tomorrow",
        user_message=(
            "Remind me tomorrow at 9:00 AM UTC to call Bob about the contract. "
            "Schedule it now using a cron that fires only on tomorrow's date."
        ),
    )

    workflow_event_types = [e["event_type"] for e in events]
    assert "WorkflowCompleted" in workflow_event_types, (
        f"workflow did not finish cleanly; events: {workflow_event_types}"
    )

    calls = _trigger_create_calls(events)
    assert calls, (
        "agent never produced a successful triggers.create_cron call; "
        f"events seen: {workflow_event_types}"
    )

    rows = _cron_rows_for_agent(agent_id)
    assert rows, f"no cron rows landed in triggers table for agent {agent_id}"
    row = rows[0]
    cron = row["cron_expression"]
    parts = cron.split()
    assert len(parts) in (5, 6), f"unexpected cron field count: {cron!r}"
    minute, hour, dom, month, _dow = parts[:5]
    assert hour == "9", f"expected 9am hour, got cron {cron!r}"
    assert minute in ("0", "00"), f"expected zero minute, got cron {cron!r}"
    assert dom == str(tomorrow.day), (
        f"expected day-of-month={tomorrow.day} for tomorrow, got cron {cron!r}"
    )
    assert month in (str(tomorrow.month), "*"), (
        f"expected month={tomorrow.month} (or wildcard) for tomorrow, "
        f"got cron {cron!r}"
    )
