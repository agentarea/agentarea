"""Which events a subscription receives: a kind and field filter, no code."""

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .enums import SubscriptionKind


class FilteredEvent(Protocol):
    """What a filter reads of an event."""

    @property
    def type(self) -> str: ...

    @property
    def data(self) -> dict[str, Any]: ...

    @property
    def source_type(self) -> str | None: ...

    @property
    def session_key(self) -> str | None: ...


def _kind_matches(kind: str, allowed: str) -> bool:
    return kind == allowed or kind.startswith(f"{allowed}.") or allowed.startswith(f"{kind}.")


def value_at(data: dict[str, Any], path: str) -> Any:
    """The value at a dotted ``path`` in event data, or ``None``.

    A generic webhook used to carry its body twice, as ``body`` and
    ``raw_data``; it now carries ``raw_data`` only. A filter or condition
    written against ``body.*`` still reads that copy.
    """
    parts = path.split(".")
    if parts[0] == "body" and "body" not in data and "raw_data" in data:
        parts[0] = "raw_data"
    value: Any = data
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class EventFilter(BaseModel):
    """Empty kinds and fields match every event."""

    model_config = ConfigDict(extra="forbid")

    kinds: list[str] = Field(default_factory=list)
    fields: dict[str, Any] = Field(default_factory=dict)

    def matches(self, kind: str, data: dict[str, Any]) -> bool:
        if self.kinds and not any(_kind_matches(kind, allowed) for allowed in self.kinds):
            return False
        return all(value_at(data, path) == expected for path, expected in self.fields.items())

    def admits(self, event: FilteredEvent) -> bool:
        return self.matches(event.type, event.data)

    @classmethod
    def from_trigger_event_types(cls, event_types: list[str] | None) -> "EventFilter":
        return cls(kinds=list(event_types or []))


class ExternalFilter(EventFilter):
    """An MCP Events subscriber's arguments: a kind prefix, a source type, a session."""

    source_type: str | None = None
    session_key: str | None = None

    def admits(self, event: FilteredEvent) -> bool:
        return (
            super().admits(event)
            and (self.source_type is None or event.source_type == self.source_type)
            and (self.session_key is None or event.session_key == self.session_key)
        )


def filter_for(kind: SubscriptionKind, stored: dict[str, Any]) -> EventFilter:
    """The filter a subscription of ``kind`` stored."""
    if kind is SubscriptionKind.EXTERNAL:
        return ExternalFilter.model_validate(stored)
    return EventFilter.model_validate(stored)
