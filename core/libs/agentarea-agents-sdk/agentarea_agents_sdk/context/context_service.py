from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ContextEvent:
    """Minimal event record stored in context service.

    We intentionally keep this generic. Later we can map to Message objects
    when preparing LLM history.
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: time.time())
    task_id: str | None = None


class ContextService(Protocol):
    async def append_event(self, task_id: str, event: ContextEvent) -> None: ...
    async def list_events(self, task_id: str, limit: int | None = None) -> list[ContextEvent]: ...
    async def set_state(self, task_id: str, key: str, value: Any) -> None: ...
    async def get_state(self, task_id: str, key: str, default: Any | None = None) -> Any: ...


class InMemoryContextService:
    """In-memory implementation keyed by task_id.

    - Stores append-only event logs per task_id
    - Stores simple per-task state dict
    """

    def __init__(self) -> None:
        self._events: dict[str, list[ContextEvent]] = {}
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def append_event(self, task_id: str, event: ContextEvent) -> None:
        async with self._lock:
            event.task_id = task_id
            self._events.setdefault(task_id, []).append(event)

    async def list_events(self, task_id: str, limit: int | None = None) -> list[ContextEvent]:
        async with self._lock:
            events = self._events.get(task_id, [])
            return events[-limit:] if limit else list(events)

    async def set_state(self, task_id: str, key: str, value: Any) -> None:
        async with self._lock:
            self._state.setdefault(task_id, {})[key] = value

    async def get_state(self, task_id: str, key: str, default: Any | None = None) -> Any:
        async with self._lock:
            return self._state.get(task_id, {}).get(key, default)


# Helper: turn EventAgent events into persisted ContextEvents
from collections.abc import Awaitable, Callable  # noqa: E402


def create_context_event_listener(
    context_service: ContextService, task_id: str
) -> Callable[[Any], Any | Awaitable[Any]]:
    """Create an event listener that mirrors agent events into the context service.

    This keeps EventAgent decoupled. If a different ContextService is injected,
    it should still be compatible with the Protocol.
    """

    async def _listener(evt: Any) -> None:
        try:
            # evt is EventAgent.Event with fields: type, payload
            await context_service.append_event(
                task_id,
                ContextEvent(
                    type=getattr(evt, "type", "event"), payload=getattr(evt, "payload", {})
                ),
            )
        except Exception:  # noqa: S110
            # best-effort persistence – do not crash agent flow
            pass

    return _listener


# Optional: utility to map persisted ContextEvents into LLM message history
# We keep it minimal for now (user asked to add richer mapping later)


def events_to_messages(events: list[ContextEvent]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    pending_tool_calls: list[dict[str, Any]] | None = None
    for ev in events:
        if ev.type == "assistant_message":
            content = ev.payload.get("content", "")
            tool_calls = ev.payload.get("tool_calls") or pending_tool_calls
            msg: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)
            pending_tool_calls = None
        elif ev.type == "llm_tool_calls_detected":
            tool_calls = ev.payload.get("tool_calls")
            if tool_calls:
                # Defer attaching tool_calls to the next assistant_message if present;
                # otherwise we'll append a minimal assistant message at the end.
                pending_tool_calls = tool_calls
        elif ev.type == "tool_execution_finished":
            # When tool returns result we also have the tool_call_id and name
            tool_name = ev.payload.get("tool_name")
            tool_call_id = ev.payload.get("tool_call_id")
            result = ev.payload.get("result")
            if tool_name and tool_call_id is not None:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": str(result),
                    }
                )
        elif ev.type == "tool_execution_error":
            # Mirror tool error as a tool message so the model can see failures when replaying
            tool_name = ev.payload.get("tool_name")
            tool_call_id = ev.payload.get("tool_call_id")
            error = ev.payload.get("error")
            if tool_name and tool_call_id is not None:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": f"Error: {error}",
                    }
                )
        elif ev.type in {
            "llm_chunk",
            "iteration_started",
            "iteration_finished",
            "agent_completed",
            "llm_request",
            "tool_execution_started",
            "completion_signaled",
        }:
            # Not chat history material; skip to keep history compact
            continue
        # Add more mappings as needed later

    # If we saw tool calls but never got a final assistant message (edge cases), add a minimal one
    if pending_tool_calls:
        messages.append({"role": "assistant", "content": "", "tool_calls": pending_tool_calls})

    return messages
