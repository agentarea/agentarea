from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict
from uuid import UUID, uuid4


@dataclass
class DomainEvent:
    event_id: UUID
    timestamp: datetime
    event_type: str
    data: Dict[str, Any]

    def __init__(self, **kwargs):
        self.event_id = kwargs.get('event_id', uuid4())
        self.timestamp = kwargs.get('timestamp', datetime.utcnow())
        self.event_type = self.__class__.__name__
        self.data = kwargs 