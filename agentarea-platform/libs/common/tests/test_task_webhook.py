"""The task webhook body and its signature."""

import hashlib
import hmac
import json

from agentarea_common.utils.task_webhook import build_task_webhook_body, sign


def _event(event_type: str, **data) -> dict:
    return {
        "event_type": event_type,
        "event_id": "ev-1",
        "timestamp": "2026-10-12T10:00:00+00:00",
        "task_id": "t-1",
        "data": {"task_id": "t-1", **data},
    }


def test_a_completed_turn_reports_cost_tokens_and_the_end_user():
    body = json.loads(
        build_task_webhook_body(
            _event(
                "task.completed",
                total_cost="0.0123",
                tokens_used=4200,
                result="Готово",
                execution_status="waiting",
                end_user_id="eu-7",
                app_metadata={"chatId": "c-1"},
            )
        )
        or ""
    )

    assert body["type"] == "task.completed"
    assert body["status"] == "completed"
    assert body["execution_status"] == "waiting"
    assert body["total_cost"] == "0.0123"
    assert body["tokens_used"] == 4200
    assert body["end_user_id"] == "eu-7"
    assert body["metadata"] == {"chatId": "c-1"}
    assert body["result"] == "Готово"
    assert body["event_id"] == "ev-1"


def test_only_terminal_events_are_delivered():
    assert build_task_webhook_body(_event("tool.call")) is None
    assert build_task_webhook_body(_event("task.awaiting_follow_up")) is None
    assert json.loads(build_task_webhook_body(_event("task.failed", error="x")) or "")[
        "status"
    ] == "failed"


def test_the_signature_is_hmac_sha256_of_timestamp_dot_body():
    secret, body = "s" * 32, '{"a":1}'
    expected = hmac.new(secret.encode(), b'1700000000.{"a":1}', hashlib.sha256).hexdigest()

    assert sign(secret, body, 1700000000) == f"t=1700000000,v1={expected}"
