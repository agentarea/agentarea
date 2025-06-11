from typing import Annotated
from fastapi import Depends

from ...common.events.broker import EventBroker


# Global fallback for testing
_test_event_broker: EventBroker | None = None


async def get_event_broker() -> EventBroker:
    """FastAPI dependency to get EventBroker instance from application state."""
    global _test_event_broker
    
    # Try to get from application state first
    try:
        from ...main import app_state
        if app_state.event_broker is not None:
            return app_state.event_broker
    except ImportError:
        # If main app is not available, use test broker
        pass
    
    # Try to get from test app state
    try:
        import sys
        if 'test_events_app' in sys.modules:
            test_app_module = sys.modules['test_events_app']
            if hasattr(test_app_module, 'app_state') and test_app_module.app_state.event_broker is not None:
                return test_app_module.app_state.event_broker
    except Exception:
        pass
    
    # Fallback to global test broker
    if _test_event_broker is None:
        _test_event_broker = EventBroker()
    
    return _test_event_broker


# Type alias for dependency injection (following your existing pattern)
EventBrokerDep = Annotated[EventBroker, Depends(get_event_broker)]
