from agentarea.common.events.router import get_event_router
from agentarea.config import get_settings
from .task_events import register_task_event_handlers
from .mcp_events import register_mcp_event_handlers

router = get_event_router(
    settings=get_settings().broker,
)

# Register event handlers with the router
register_task_event_handlers(router)
register_mcp_event_handlers(router)

# Task event handlers are now registered during application startup
# with proper dependency injection in main.py
