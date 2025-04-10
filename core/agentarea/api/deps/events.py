from typing import Annotated

from fastapi import Depends

from ...common.events.broker import EventBroker

_event_broker = None

async def get_event_broker() -> EventBroker:
    global _event_broker
    if _event_broker is None:
        _event_broker = EventBroker()
    return _event_broker