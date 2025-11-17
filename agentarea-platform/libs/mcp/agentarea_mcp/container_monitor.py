"""Container monitoring service for MCP infrastructure.

This service periodically checks the health of MCP containers and publishes
status change events to notify other parts of the system.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from agentarea_common.config import get_settings
from agentarea_common.events.broker import EventBroker

from .domain.events import MCPServerInstanceUpdated

logger = logging.getLogger(__name__)


class ContainerHealthStatus:
    """Represents the health status of a container."""

    def __init__(self, service_name: str, is_healthy: bool, status: str, timestamp: datetime):
        self.service_name = service_name
        self.is_healthy = is_healthy
        self.status = status
        self.timestamp = timestamp
        self.last_check = timestamp

    def __str__(self):
        """Return human-readable container health summary."""
        return (
            f"ContainerHealthStatus(service='{self.service_name}', "
            f"healthy={self.is_healthy}, status='{self.status}')"
        )


class MCPContainerMonitor:
    """Monitor MCP containers and publish health status changes."""

    def __init__(self, event_broker: EventBroker, check_interval: int = 30):
        """Initialize the container monitor.

        Args:
            event_broker: Event broker for publishing status changes
            check_interval: How often to check container health (seconds)
        """
        self.event_broker = event_broker
        self.check_interval = check_interval
        self.container_statuses: dict[str, ContainerHealthStatus] = {}
        self.is_running = False
        self.settings = get_settings()

        # MCP Manager URL from settings
        self.mcp_manager_url = getattr(self.settings, "MCP_MANAGER_URL", "http://localhost:7999")

        logger.info(f"MCPContainerMonitor initialized with check_interval={check_interval}s")

    async def start(self):
        """Start the monitoring loop."""
        if self.is_running:
            logger.warning("Monitor is already running")
            return

        self.is_running = True
        logger.info("Starting MCP container monitoring...")

        while self.is_running:
            try:
                await self._check_all_containers()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(min(self.check_interval, 10))  # Shorter retry interval on error

    async def stop(self):
        """Stop the monitoring loop."""
        self.is_running = False
        logger.info("Stopping MCP container monitoring...")

    async def _check_all_containers(self):
        """Check health status of all containers."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Get list of all containers
                response = await client.get(f"{self.mcp_manager_url}/containers")
                if response.status_code != 200:
                    logger.error(f"Failed to get container list: {response.status_code}")
                    return

                containers_data = response.json()
                containers = containers_data.get("containers", [])

                logger.debug(f"Checking health of {len(containers)} containers")

                for container in containers:
                    await self._check_container_health(container, client)

        except Exception as e:
            logger.error(f"Failed to check containers: {e}")

    async def _check_container_health(
        self, container_data: dict[str, Any], client: httpx.AsyncClient
    ):
        """Check health of a specific container."""
        service_name = container_data.get("service_name")
        if not service_name:
            return

        try:
            # Get detailed health check
            response = await client.get(f"{self.mcp_manager_url}/containers/{service_name}/health")

            if response.status_code == 200:
                health_data = response.json()
                is_healthy = health_data.get("healthy", False)
                status = health_data.get("status", "unknown")
            elif response.status_code == 503:  # Service Unavailable = unhealthy
                health_data = response.json()
                is_healthy = False
                status = health_data.get("status", "unhealthy")
            else:
                logger.warning(
                    f"Unexpected health check response for {service_name}: {response.status_code}"
                )
                is_healthy = False
                status = "error"

            new_health_status = ContainerHealthStatus(
                service_name=service_name,
                is_healthy=is_healthy,
                status=status,
                timestamp=datetime.now(),
            )

            # Check if status changed
            await self._handle_status_change(new_health_status)

        except Exception as e:
            logger.error(f"Failed to check health for container {service_name}: {e}")
            # Create error status
            error_status = ContainerHealthStatus(
                service_name=service_name,
                is_healthy=False,
                status="error",
                timestamp=datetime.now(),
            )
            await self._handle_status_change(error_status)

    async def _handle_status_change(self, new_status: ContainerHealthStatus):
        """Handle status changes and publish events if needed."""
        service_name = new_status.service_name
        previous_status = self.container_statuses.get(service_name)

        # Update stored status
        self.container_statuses[service_name] = new_status

        # Check if this is a status change
        if previous_status is None:
            logger.info(f"Initial status for {service_name}: {new_status}")
            # Publish initial status
            await self._publish_status_event(new_status, "initial")
        elif (
            previous_status.is_healthy != new_status.is_healthy
            or previous_status.status != new_status.status
        ):
            logger.info(
                f"Status change for {service_name}: {previous_status.status} -> {new_status.status}"
            )
            await self._publish_status_event(new_status, "changed")
        else:
            logger.debug(f"No change for {service_name}: {new_status}")

    async def _publish_status_event(self, status: ContainerHealthStatus, change_type: str):
        """Publish a status change event."""
        try:
            # Create status mapping
            status_mapping = {
                "running": "running",
                "stopped": "stopped",
                "error": "error",
                "starting": "pending",
                "stopping": "stopping",
            }
            mapped_status = status_mapping.get(status.status, "error")

            # Publish MCPServerInstanceUpdated event
            # Generate a UUID from service name for consistency
            import hashlib

            service_uuid = UUID(hashlib.md5(status.service_name.encode()).hexdigest())  # noqa: S324

            event = MCPServerInstanceUpdated(
                instance_id=service_uuid,
                server_spec_id=None,  # We don't have this information from container data
                name=status.service_name,
                status=mapped_status,
            )

            await self.event_broker.publish(event)

            logger.info(
                f"Published status event for {status.service_name}: {mapped_status} ({change_type})"
            )

        except Exception as e:
            logger.error(f"Failed to publish status event for {status.service_name}: {e}")

    def get_all_statuses(self) -> list[ContainerHealthStatus]:
        """Get current health status of all monitored containers."""
        return list(self.container_statuses.values())

    def get_container_status(self, service_name: str) -> ContainerHealthStatus | None:
        """Get current health status of a specific container."""
        return self.container_statuses.get(service_name)

    def get_summary(self) -> dict[str, Any]:
        """Get monitoring summary statistics."""
        total = len(self.container_statuses)
        healthy = sum(1 for status in self.container_statuses.values() if status.is_healthy)
        unhealthy = total - healthy

        return {
            "total_containers": total,
            "healthy_containers": healthy,
            "unhealthy_containers": unhealthy,
            "is_monitoring": self.is_running,
            "check_interval": self.check_interval,
            "last_check": max(
                (status.last_check for status in self.container_statuses.values()), default=None
            ),
        }


# Global monitor instance
_monitor_instance: MCPContainerMonitor | None = None


async def get_container_monitor(event_broker: EventBroker) -> MCPContainerMonitor:
    """Get or create the global container monitor instance."""
    global _monitor_instance

    if _monitor_instance is None:
        _monitor_instance = MCPContainerMonitor(event_broker)

    return _monitor_instance


async def start_container_monitoring(event_broker: EventBroker) -> MCPContainerMonitor:
    """Start container monitoring with the global instance."""
    monitor = await get_container_monitor(event_broker)

    # Start monitoring in background task
    task = asyncio.create_task(monitor.start())
    # Store task reference to prevent garbage collection
    monitor._background_task = task

    return monitor


async def stop_container_monitoring():
    """Stop container monitoring."""
    global _monitor_instance

    if _monitor_instance and _monitor_instance.is_running:
        await _monitor_instance.stop()
