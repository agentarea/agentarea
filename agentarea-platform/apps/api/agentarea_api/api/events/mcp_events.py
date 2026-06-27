"""MCP event handlers using existing EventBroker architecture.

Lifecycle is owned by the substrate (Go MCP manager + Docker); Python's
`verify()` function + `container_monitor.py` sweep handle tool discovery and
orphan cleanup. This Redis subscriber remains for observability logging of
status-change events emitted by the Go MCP Manager.
"""

import logging
from typing import Any

from faststream.redis.fastapi import RedisRouter

logger = logging.getLogger(__name__)


def register_mcp_event_handlers(router: RedisRouter) -> None:
    """Register MCP event handlers with the FastStream router."""

    @router.subscriber("MCPServerInstanceStatusChanged")
    async def handle_instance_status_change(message: dict[str, Any]) -> None:
        """Log MCP server instance status change events from Go MCP Manager.

        Status persistence and tool discovery are handled by Temporal workflows.
        This handler remains for observability.
        """
        logger.info(f"Received MCPServerInstanceStatusChanged event: {message}")

        try:
            event_data = message.get("data", {})
            if isinstance(event_data, dict) and "data" in event_data:
                status_data = event_data["data"]
            else:
                status_data = event_data

            instance_id = status_data.get("instance_id")
            status = status_data.get("status")
            container_id = status_data.get("container_id")
            url = status_data.get("url")

            if not instance_id:
                logger.warning("MCPServerInstanceStatusChanged event missing instance_id")
                return

            logger.info(
                "MCP instance %s status: %s (container=%s, url=%s)",
                instance_id,
                status,
                container_id,
                url,
            )

        except Exception as e:
            logger.error(f"Failed to handle instance status change event: {e}")

    logger.info("MCP event handlers registered")
