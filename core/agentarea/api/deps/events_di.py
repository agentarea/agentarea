"""
Alternative EventBroker dependency using Dependency Injection Container.
This demonstrates a more advanced pattern for managing dependencies.
"""
from typing import Annotated
from fastapi import Depends

from ...common.events.broker import EventBroker
from ...common.di.container import resolve


async def get_event_broker_di() -> EventBroker:
    """FastAPI dependency to get EventBroker instance from DI container."""
    return resolve(EventBroker)


# Type alias for dependency injection
EventBrokerDIDep = Annotated[EventBroker, Depends(get_event_broker_di)] 