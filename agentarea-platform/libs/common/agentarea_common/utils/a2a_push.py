"""A2A push-notification config helpers (pure, dependency-free).

Shared by the API (RPC handlers) and the worker (delivery adapter) so the two
sides agree on storage layout, the secret key for the callback token, and the
notification body shape. See docs/adr/2026-06-20-a2a-push-notifications.md.

Storage layout (mirrors how channels are stored):
- Non-secret config (id, url, presentation) lives in
  ``task.task_parameters["a2a_push_configs"]`` — a list of dicts.
- The callback ``token`` is NEVER stored here; it goes to the secret store under
  ``a2a_push_token:<task_id>:<config_id>`` and is never returned by get/list.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from agentarea_common.events.contract import (
    TASK_CANCELLED,
    TASK_COMPLETED,
    TASK_FAILED,
    canonical_type,
)

PUSH_CONFIGS_PARAM_KEY = "a2a_push_configs"

# Maps canonical workflow terminal event types to A2A v1.0.0 task states (proto
# encoding). The incoming event_type is canonicalized before lookup, so legacy
# and canonical names both resolve.
_TERMINAL_EVENT_STATES = {
    TASK_COMPLETED: "COMPLETED",
    TASK_FAILED: "FAILED",
    TASK_CANCELLED: "CANCELED",
}


def push_token_secret_name(task_id: str, config_id: str) -> str:
    """Secret-store key for a push config's callback token."""
    return f"a2a_push_token:{task_id}:{config_id}"


def list_push_configs(parameters: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return the stored (non-secret) push configs for a task."""
    if not parameters:
        return []
    configs = parameters.get(PUSH_CONFIGS_PARAM_KEY)
    return list(configs) if isinstance(configs, list) else []


def upsert_push_config(
    parameters: dict[str, Any] | None, url: str, config_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Insert or replace a push config (by id) in task parameters.

    Returns ``(new_parameters, stored_config)``. The stored config holds only
    non-secret fields; ``config_id`` is generated when absent.
    """
    params = dict(parameters or {})
    configs = list(list_push_configs(params))
    cfg_id = config_id or uuid4().hex
    stored = {"id": cfg_id, "url": url}
    configs = [c for c in configs if c.get("id") != cfg_id]
    configs.append(stored)
    params[PUSH_CONFIGS_PARAM_KEY] = configs
    return params, stored


def get_push_config(parameters: dict[str, Any] | None, config_id: str) -> dict[str, Any] | None:
    """Return a single stored push config by id, or None."""
    for cfg in list_push_configs(parameters):
        if cfg.get("id") == config_id:
            return cfg
    return None


def delete_push_config(
    parameters: dict[str, Any] | None, config_id: str
) -> tuple[dict[str, Any], bool]:
    """Remove a push config by id. Returns ``(new_parameters, removed)``."""
    params = dict(parameters or {})
    configs = list_push_configs(params)
    remaining = [c for c in configs if c.get("id") != config_id]
    params[PUSH_CONFIGS_PARAM_KEY] = remaining
    return params, len(remaining) != len(configs)


def task_push_config_result(task_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Build a flat A2A v1.0.0 ``TaskPushNotificationConfig`` result (token omitted)."""
    return {
        "taskId": str(task_id),
        "id": config.get("id"),
        "url": config.get("url"),
    }


def build_push_notification_body(event: dict[str, Any]) -> str | None:
    """Build the A2A v1.0.0 notification JSON body for a workflow event.

    Returns a serialized StreamResponse ``statusUpdate`` wrapper for terminal
    events, or None for events that should not be pushed.

    ``event`` is the delivery-side shape: ``{event_type, event_id, task_id, data}``
    with the workflow payload in ``data`` (unprefixed event types).
    """
    import json

    event_type = canonical_type(event.get("event_type", ""))
    state = _TERMINAL_EVENT_STATES.get(event_type)
    if not state:
        return None

    data = event.get("data") or {}
    task_id = str(data.get("task_id") or event.get("task_id") or "")
    context_id = str(data.get("context_id") or task_id)
    text = data.get("result") or data.get("final_response") or data.get("error") or ""

    status: dict[str, Any] = {"state": state}
    if text:
        status["message"] = {
            "role": "AGENT",
            "messageId": uuid4().hex,
            "parts": [{"text": str(text)}],
        }

    body = {
        "statusUpdate": {
            "taskId": task_id,
            "contextId": context_id,
            "status": status,
        }
    }
    return json.dumps(body)
