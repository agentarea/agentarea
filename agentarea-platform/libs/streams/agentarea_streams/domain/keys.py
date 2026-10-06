"""Identities derived from a stream and a key, so a retry names the same thing."""

import json
from typing import Any
from uuid import UUID, uuid5

MAX_EVENT_BYTES = 256 * 1024
STREAM_EVENT_NAMESPACE = UUID("6f1c7b8e-3d2a-4f5e-9b0c-1a2b3c4d5e6f")
_TASK_NAMESPACE = UUID("0b6a6f2e-9a51-4c43-8f3e-2d7c1e5a9b40")


def event_id_for(stream_id: UUID, event_key: str) -> UUID:
    return uuid5(STREAM_EVENT_NAMESPACE, f"{stream_id}:{event_key}")


def forward_event_key(source_stream_id: UUID, sequence: int) -> str:
    return f"{source_stream_id}:{sequence}"


def task_id_for(subscription_id: UUID, sequence: int) -> UUID:
    return uuid5(_TASK_NAMESPACE, f"{subscription_id}:{sequence}")


def encoded_size(data: dict[str, Any]) -> int:
    return len(json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str).encode())
