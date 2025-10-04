import logging

from agentarea_common.config import get_settings
from agentarea_common.events.router import get_event_router

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
        logger.info("FastStream Redis broker connected successfully")
    except Exception as e:
        logger.error(f"Failed to connect FastStream Redis broker: {e}")


async def stop_events_router():
    """Stop the FastStream router's broker with thorough cleanup."""
    try:
        # Close the broker
        await router.broker.close()

        # Additional cleanup for any remaining connections
        if hasattr(router.broker, "_connection") and router.broker._connection:
            try:
                await router.broker._connection.close()
            except Exception as conn_e:
                logger.debug(f"Error closing router broker connection: {conn_e}")

        # Force cleanup of any connection pools
        if hasattr(router.broker, "_pool") and router.broker._pool:
            try:
                router.broker._pool.close()
                await router.broker._pool.wait_closed()
            except Exception as pool_e:
                logger.debug(f"Error closing connection pool: {pool_e}")
        logger.info("FastStream Redis broker closed")
    except Exception as e:
        logger.warning(f"Error closing FastStream Redis broker: {e}")
