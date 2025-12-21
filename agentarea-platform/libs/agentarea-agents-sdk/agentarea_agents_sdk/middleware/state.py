"""State backend for agent execution."""

from typing import Any, Protocol


class StateBackend(Protocol):
    """Protocol for state persistence."""

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from state."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Set value in state."""
        ...

    def update(self, updates: dict[str, Any]) -> None:
        """Update multiple values."""
        ...

    def snapshot(self) -> dict:
        """Get full state snapshot."""
        ...


class InMemoryState:
    """In-memory state backend."""

    def __init__(self):
        self._data: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, updates: dict[str, Any]) -> None:
        self._data.update(updates)

    def snapshot(self) -> dict:
        return self._data.copy()
