"""Which events a subscription receives: a kind and field filter, no code."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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

    @classmethod
    def from_trigger_event_types(cls, event_types: list[str] | None) -> "EventFilter":
        return cls(kinds=list(event_types or []))
