"""Identities derived from a stream and a key, so a retry names the same thing."""

import json
from typing import Any
from uuid import UUID, uuid5

#: A body larger than this, encoded, is moved to the workspace's files and referenced.
MAX_INLINE_BODY_BYTES = 64 * 1024
#: The largest request a source may deliver.
MAX_REQUEST_BYTES = 25 * 1024 * 1024
STREAM_EVENT_NAMESPACE = UUID("6f1c7b8e-3d2a-4f5e-9b0c-1a2b3c4d5e6f")
_TASK_NAMESPACE = UUID("0b6a6f2e-9a51-4c43-8f3e-2d7c1e5a9b40")


def event_id_for(stream_id: UUID, event_key: str) -> UUID:
    return uuid5(STREAM_EVENT_NAMESPACE, f"{stream_id}:{event_key}")


def derived_event_id(processor_id: UUID, source_event_id: UUID) -> UUID:
    """What a processor writes for one source event; a retry names the same event."""
    return uuid5(processor_id, str(source_event_id))


def task_id_for(subscription_id: UUID, event_id: UUID) -> UUID:
    return uuid5(_TASK_NAMESPACE, f"{subscription_id}:{event_id}")


def encoded_size(data: dict[str, Any]) -> int:
    return len(json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str).encode())
