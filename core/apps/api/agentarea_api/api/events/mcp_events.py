"""MCP event handlers using existing EventBroker architecture."""

import logging
from typing import Any

from agentarea_mcp.events import MCPEventType
from faststream.redis.fastapi import RedisRouter

logger = logging.getLogger(__name__)


def register_mcp_event_handlers(router: RedisRouter) -> None:
    """Register MCP event handlers with the FastStream router."""

    @router.subscriber(MCPEventType.SERVER_CREATING.value)
    async def handle_server_creating_event(message: dict[str, Any]) -> None:
        """Handle MCP server creating events from infrastructure."""
        logger.info(f"Received MCPServerCreating event: {message}")

        try:
            # Extract event data
            event_data = message.get("data", {})
            config_id = event_data.get("config_id") or message.get("config_id")
            runtime_id = event_data.get("runtime_id") or message.get("runtime_id")

            if not config_id:
                logger.warning("MCPServerCreating event missing config_id")
                return

            # Update instance status to "creating"

            # Note: In real implementation, we'd properly inject dependencies
            # For now, this is a placeholder for the event handling pattern
            logger.info(f"MCP server {config_id} is creating with runtime {runtime_id}")

        except Exception as e:
            logger.error(f"Failed to handle server creating event: {e}")

    @router.subscriber(MCPEventType.SERVER_READY.value)
    async def handle_server_ready_event(message: dict[str, Any]) -> None:
        """Handle MCP server ready events from infrastructure."""
        logger.info(f"Received MCPServerReady event: {message}")

        try:
            event_data = message.get("data", {})
            config_id = event_data.get("config_id") or message.get("config_id")
            endpoint = event_data.get("endpoint") or message.get("endpoint")

            if not config_id:
                logger.warning("MCPServerReady event missing config_id")
                return

            logger.info(f"MCP server {config_id} is ready at {endpoint}")

        except Exception as e:
            logger.error(f"Failed to handle server ready event: {e}")

    @router.subscriber(MCPEventType.SERVER_FAILED.value)
    async def handle_server_failed_event(message: dict[str, Any]) -> None:
        """Handle MCP server failed events from infrastructure."""
        logger.info(f"Received MCPServerFailed event: {message}")

        try:
            event_data = message.get("data", {})
            config_id = event_data.get("config_id") or message.get("config_id")
            error_message = event_data.get("error_message") or message.get("error_message")

            if not config_id:
                logger.warning("MCPServerFailed event missing config_id")
                return

            logger.error(f"MCP server {config_id} failed: {error_message}")

        except Exception as e:
            logger.error(f"Failed to handle server failed event: {e}")

    @router.subscriber(MCPEventType.SERVER_STOPPED.value)
    async def handle_server_stopped_event(message: dict[str, Any]) -> None:
        """Handle MCP server stopped events from infrastructure."""
        logger.info(f"Received MCPServerStopped event: {message}")

        try:
            event_data = message.get("data", {})
            config_id = event_data.get("config_id") or message.get("config_id")
            reason = event_data.get("reason") or message.get("reason", "unknown")

            if not config_id:
                logger.warning("MCPServerStopped event missing config_id")
                return

            logger.info(f"MCP server {config_id} stopped: {reason}")

        except Exception as e:
            logger.error(f"Failed to handle server stopped event: {e}")

    @router.subscriber("MCPServerInstanceStatusChanged")
    async def handle_instance_status_change(message: dict[str, Any]) -> None:
        """Handle MCP server instance status change events from MCP Manager."""
        logger.info(f"Received MCPServerInstanceStatusChanged event: {message}")

        try:
            # Extract event data from the FastStream message format
            event_data = message.get("data", {})
            if isinstance(event_data, dict) and "data" in event_data:
                # Unwrap nested data structure
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

            logger.info(f"Updating MCP instance {instance_id} status to {status}")

            # TODO: Update instance status in database
            # This would require injecting the MCP instance service
            # For now, this is a placeholder that logs the event
            logger.info(f"MCP instance {instance_id} status updated to {status}")
            if container_id:
                logger.info(f"Container ID: {container_id}")
            if url:
                logger.info(f"Instance URL: {url}")

        except Exception as e:
            logger.error(f"Failed to handle instance status change event: {e}")

    logger.info("✅ MCP event handlers registered")
