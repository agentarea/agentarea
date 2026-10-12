"""Task webhook: tell the API caller a task's turn ended, with what it cost.

Shared by the API (stores the config when a task is created) and the worker
(formats and sends the delivery), so both agree on where the config lives, the
secret's name, the body and the signature.

- The config (``{"url", "signed"}``) is trusted task metadata under
  ``task_webhook``; only an API key or service client may set it.
- The signing secret is in the secret store as ``task_webhook:<task_id>`` and is
  never returned.
- A delivery is a POST of :func:`build_task_webhook_body` for each terminal
  event (``task.completed``, ``task.failed``, ``task.cancelled``), signed as
  ``X-AgentArea-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "<t>.<body>">``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from agentarea_common.events.contract import (
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    canonical_type,
)

TASK_WEBHOOK_KEY = "task_webhook"
SIGNATURE_HEADER = "X-AgentArea-Signature"
EVENT_HEADER = "X-AgentArea-Event"
DELIVERY_HEADER = "X-AgentArea-Delivery"
WEBHOOK_VERSION = "1"

_TERMINAL = {TASK_COMPLETED, TASK_FAILED, TASK_CANCELLED}
_STATUS = {TASK_COMPLETED: "completed", TASK_FAILED: "failed", TASK_CANCELLED: "cancelled"}


def webhook_secret_name(task_id: str) -> str:
    """Secret-store key for a task webhook's signing secret."""
    return f"task_webhook:{task_id}"


def sign(secret: str, body: str, timestamp: int) -> str:
    """The ``X-AgentArea-Signature`` value for ``body`` sent at ``timestamp``."""
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def build_task_webhook_body(event: dict[str, Any]) -> str | None:
    """The JSON body for a terminal task event, or None for any other event.

    ``event`` is the delivery-side shape ``{event_type, event_id, timestamp,
    task_id, data}``;
    ``data`` carries the workflow payload plus the task's ``end_user_id`` and
    ``app_metadata`` added by the publisher.

    ``task.completed`` ends every turn of a conversation, so a task that takes
    follow-ups sends one per turn. ``total_cost`` and ``tokens_used`` are the
    task's running totals, never per turn: charge the difference from the last
    delivery you processed for the task.
    """
    event_type = canonical_type(event.get("event_type", ""))
    if event_type not in _TERMINAL:
        return None
    data = event.get("data") or {}
    body = {
        "version": WEBHOOK_VERSION,
        "type": event_type,
        "event_id": event.get("event_id"),
        "task_id": str(data.get("task_id") or event.get("task_id") or ""),
        "agent_id": data.get("agent_id"),
        "execution_id": data.get("execution_id"),
        "status": _STATUS[event_type],
        # "waiting": the task takes a follow-up; "completed": the run is over.
        "execution_status": data.get("execution_status"),
        "end_user_id": data.get("end_user_id"),
        "metadata": data.get("app_metadata"),
        "total_cost": data.get("total_cost"),
        "tokens_used": data.get("tokens_used"),
        "result": data.get("result") or data.get("final_response"),
        "error": data.get("error"),
        "failure_reason": data.get("failure_reason"),
        "timestamp": event.get("timestamp") or data.get("timestamp"),
    }
    return json.dumps(body, separators=(",", ":"), default=str)
