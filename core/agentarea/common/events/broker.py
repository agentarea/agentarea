from collections import defaultdict
from typing import Callable, Type

from .base_events import DomainEvent


class EventBroker:
    def __init__(self):
        self._subscribers: dict[Type[DomainEvent], list[Callable]] = defaultdict(list)
        
    async def publish(self, event: DomainEvent):
        """Publish an event to all subscribers"""
        event_type = type(event)
        for handler in self._subscribers[event_type]:
            await handler(event)
            
    def subscribe(self, event_type: Type[DomainEvent], handler: Callable):
        """Subscribe a handler to an event type"""
        self._subscribers[event_type].append(handler)
        
    def unsubscribe(self, event_type: Type[DomainEvent], handler: Callable):
        """Unsubscribe a handler from an event type"""
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler) 

def get_event_broker() -> EventBroker:
    return EventBroker()
