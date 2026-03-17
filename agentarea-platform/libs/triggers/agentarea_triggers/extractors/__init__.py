"""Data extractors for poll-based inbound channels."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ExtractionResult:
    """Result of a data extraction operation."""

    has_new_data: bool
    events: list[dict[str, Any]] = field(default_factory=list)
    updated_state: dict[str, Any] = field(default_factory=dict)
    channel_origin: dict[str, Any] = field(default_factory=dict)


class DataExtractor(Protocol):
    """Protocol for poll-based data extraction.

    Extractors fetch new data from external sources (email, RSS, APIs)
    and return normalized events with channel origin metadata.
    """

    async def extract(
        self, config: dict[str, Any], state: dict[str, Any] | None
    ) -> ExtractionResult:
        """Extract new data from source.

        Args:
            config: Connection/auth details for the source.
            state: Previous cursor/checkpoint (None on first run).

        Returns:
            ExtractionResult with new events and updated state.
        """
        ...


# Registry of available extractors
_EXTRACTORS: dict[str, type] = {}


def register_extractor(name: str, cls: type) -> None:
    """Register a data extractor implementation."""
    _EXTRACTORS[name] = cls


def get_extractor(name: str) -> type | None:
    """Get a registered extractor class by name."""
    return _EXTRACTORS.get(name)


def list_extractors() -> list[str]:
    """List all registered extractor names."""
    return list(_EXTRACTORS.keys())
