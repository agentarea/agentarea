from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .base_events import DomainEvent, EventEnvelope

if TYPE_CHECKING:
    from .event_models import BaseEvent


class EventBroker(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent | EventEnvelope | BaseEvent) -> None:
        """Publish an event through the broker.

        Supports DomainEvent (legacy), EventEnvelope, or typed BaseEvent models.
        """
        raise NotImplementedError

    async def subscribe(self, pattern: str) -> None:
        """Subscribe to events matching a pattern.

        Default implementation is not provided. Subclasses may override to add
        subscription support.
        """
        raise NotImplementedError("subscribe is not implemented for this broker")
