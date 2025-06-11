from abc import ABC, abstractmethod

from .base_events import DomainEvent


class EventBroker(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent):
        raise NotImplementedError


def get_event_broker() -> EventBroker:
    return EventBroker()
