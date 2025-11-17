from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass
class DomainEvent:
    event_id: UUID
    timestamp: datetime
    event_type: str
    data: dict[str, Any]

    def __init__(self, **kwargs: Any) -> None:
        self.event_id = kwargs.get("event_id", uuid4())
        self.timestamp = kwargs.get("timestamp", datetime.now(UTC))
        # Use provided event_type or fallback to class name
        self.event_type = kwargs.get("event_type", self.__class__.__name__)
        self.data = kwargs


# --- Pydantic models for event envelope (non-breaking addition) ---
# We keep the legacy DomainEvent dataclass while introducing a typed Pydantic
# envelope that can be used across brokers, SSE, and persistence layers.

from pydantic import BaseModel, Field, field_serializer  # noqa: E402


class EventEnvelope(BaseModel):
    """Pydantic event envelope compatible with existing DomainEvent usage.

    The shape matches our current on-the-wire format:
    {
        "event_id": UUID,
        "timestamp": datetime (ISO in JSON),
        "event_type": str,
        "data": dict[str, Any]
    }

    Notes:
    - We intentionally keep all custom fields (aggregate_id, original_event_type,
      original_timestamp, original_data, etc.) inside `data` to remain compatible
      with existing consumers (API, CLI, frontend) that expect them in `data`.
    - Use `from_any` to convert from DomainEvent instances or raw dicts.
    """

    event_id: UUID = Field(default_factory=uuid4, description="Unique event identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Event timestamp (UTC)"
    )
    event_type: str = Field(..., description="Type of the event")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime, _info):
        # Always serialize as ISO8601 with timezone info
        return value.isoformat()

    @classmethod
    def from_domain_event(cls, event: DomainEvent) -> "EventEnvelope":
        """Create envelope from legacy DomainEvent dataclass."""
        # DomainEvent.data already contains the payload kwargs
        return cls(
            event_id=event.event_id,
            timestamp=event.timestamp,
            event_type=event.event_type,
            data=event.data or {},
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EventEnvelope":
        """Create envelope from a dict; tolerant of missing fields by applying defaults."""
        # Accept either nested dicts with keys or already-normalized envelopes
        event_id = payload.get("event_id", uuid4())
        timestamp = payload.get("timestamp", datetime.now(UTC))
        event_type = payload.get("event_type") or payload.get("type") or "UnknownEvent"
        data = payload.get("data", {})
        # If the payload looks like a DomainEvent.data dict (no top-level
        # metadata), wrap it
        if data == {}:
            # Heuristic: treat payload as data when it contains
            # aggregate_id/original_event_type etc.
            known_keys = {
                "aggregate_id",
                "original_event_type",
                "original_timestamp",
                "original_data",
            }
            if any(k in payload for k in known_keys):
                data = payload
        return cls(event_id=event_id, timestamp=timestamp, event_type=event_type, data=data)

    @classmethod
    def from_any(cls, obj: "EventEnvelope | DomainEvent | dict[str, Any]") -> "EventEnvelope":
        """Coerce an object into EventEnvelope."""
        if isinstance(obj, EventEnvelope):
            return obj
        if isinstance(obj, DomainEvent):
            return cls.from_domain_event(obj)
        if isinstance(obj, dict):
            return cls.from_dict(obj)
        raise TypeError(f"Unsupported event type: {type(obj)!r}")

    def as_json_dict(self) -> dict[str, Any]:
        """Dump envelope as a JSON-ready dict (ISO timestamps, UUIDs as strings)."""
        return self.model_dump(mode="json")


def to_event_envelope(obj: "EventEnvelope | DomainEvent | dict[str, Any]") -> EventEnvelope:
    """Helper to normalize any event-like object to EventEnvelope."""
    return EventEnvelope.from_any(obj)


def dump_event_envelope(obj: "EventEnvelope | DomainEvent | dict[str, Any]") -> dict[str, Any]:
    """Helper to normalize and dump to a JSON-ready dict suitable for publish/SSE."""
    return to_event_envelope(obj).as_json_dict()
