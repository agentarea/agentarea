"""Which events a subscription receives: a kind and field filter, no code."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _kind_matches(kind: str, allowed: str) -> bool:
    return kind == allowed or kind.startswith(f"{allowed}.") or allowed.startswith(f"{kind}.")


def _value_at(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
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
        return all(_value_at(data, path) == expected for path, expected in self.fields.items())

    @classmethod
    def from_trigger_event_types(cls, event_types: list[str] | None) -> "EventFilter":
        return cls(kinds=list(event_types or []))
