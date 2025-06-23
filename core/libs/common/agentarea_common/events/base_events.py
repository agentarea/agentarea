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
        self.event_type = self.__class__.__name__
        self.data = kwargs
