from abc import ABC, abstractmethod

from .base_events import DomainEvent


class EventBroker(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError
