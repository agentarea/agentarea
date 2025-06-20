from typing import Annotated
from fastapi import Depends

from ...common.events.broker import EventBroker
from .services import get_event_broker as get_real_event_broker


async def get_event_broker() -> EventBroker:
    """FastAPI dependency to get EventBroker instance - use real implementation."""
    return await get_real_event_broker()


# Type alias for dependency injection
EventBrokerDep = Annotated[EventBroker, Depends(get_event_broker)]
