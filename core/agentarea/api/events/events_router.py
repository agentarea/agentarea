import logging

from agentarea.common.events.router import get_event_router
from agentarea.config import get_settings

from .mcp_events import register_mcp_event_handlers
from .task_events import register_task_event_handlers

logger = logging.getLogger(__name__)

router = get_event_router(
    settings=get_settings().broker,
)

# Register event handlers with the router
register_task_event_handlers(router)
register_mcp_event_handlers(router)


# Export the router for startup/shutdown handling in main.py
async def start_events_router():
    """Start the FastStream router's broker."""
    try:
        await router.broker.connect()
        print("✅ FastStream Redis broker connected successfully")
        logger.info("FastStream Redis broker connected successfully")
    except Exception as e:
        print(f"❌ Failed to connect FastStream Redis broker: {e}")
        logger.error(f"Failed to connect FastStream Redis broker: {e}")


async def stop_events_router():
    """Stop the FastStream router's broker."""
    try:
        await router.broker.close()
        print("✅ FastStream Redis broker closed")
        logger.info("FastStream Redis broker closed")
    except Exception as e:
        print(f"⚠️  Error closing FastStream Redis broker: {e}")
        logger.warning(f"Error closing FastStream Redis broker: {e}")
