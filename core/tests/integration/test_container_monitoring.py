"""Test container monitoring functionality."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from agentarea_common.testing.mocks import TestEventBroker
from agentarea_mcp.container_monitor import ContainerHealthStatus, MCPContainerMonitor


@pytest.mark.asyncio
async def test_container_monitor_initialization():
    """Test that the container monitor initializes correctly."""
    event_broker = TestEventBroker()
    monitor = MCPContainerMonitor(event_broker, check_interval=10)

    assert monitor.event_broker == event_broker
    assert monitor.check_interval == 10
    assert monitor.is_running is False
    assert len(monitor.container_statuses) == 0


@pytest.mark.asyncio
async def test_container_health_status():
    """Test ContainerHealthStatus creation and representation."""
    from datetime import datetime

    timestamp = datetime.now()
    status = ContainerHealthStatus(
        service_name="test-service", is_healthy=True, status="running", timestamp=timestamp
    )

    assert status.service_name == "test-service"
    assert status.is_healthy is True
    assert status.status == "running"
    assert status.timestamp == timestamp
    assert "test-service" in str(status)
    assert "healthy=True" in str(status)


@pytest.mark.asyncio
async def test_monitor_summary():
    """Test monitor summary statistics."""
    from datetime import datetime

    event_broker = TestEventBroker()
    monitor = MCPContainerMonitor(event_broker, check_interval=10)

    # Add some test statuses
    timestamp = datetime.now()
    monitor.container_statuses["healthy-service"] = ContainerHealthStatus(
        "healthy-service", True, "running", timestamp
    )
    monitor.container_statuses["unhealthy-service"] = ContainerHealthStatus(
        "unhealthy-service", False, "stopped", timestamp
    )

    summary = monitor.get_summary()

    assert summary["total_containers"] == 2
    assert summary["healthy_containers"] == 1
    assert summary["unhealthy_containers"] == 1
    assert summary["is_monitoring"] is False
    assert summary["check_interval"] == 10


@pytest.mark.asyncio
async def test_get_container_status():
    """Test getting status of specific containers."""
    from datetime import datetime

    event_broker = TestEventBroker()
    monitor = MCPContainerMonitor(event_broker)

    # Add a test status
    timestamp = datetime.now()
    test_status = ContainerHealthStatus("test-service", True, "running", timestamp)
    monitor.container_statuses["test-service"] = test_status

    # Test getting existing status
    status = monitor.get_container_status("test-service")
    assert status == test_status

    # Test getting non-existent status
    status = monitor.get_container_status("non-existent")
    assert status is None


@pytest.mark.asyncio
async def test_monitor_start_stop():
    """Test starting and stopping the monitor."""
    event_broker = TestEventBroker()
    monitor = MCPContainerMonitor(event_broker, check_interval=1)

    # Mock the _check_all_containers method to avoid actual HTTP calls
    monitor._check_all_containers = AsyncMock()

    # Start monitoring
    monitor_task = asyncio.create_task(monitor.start())

    # Give it a moment to start
    await asyncio.sleep(0.1)
    assert monitor.is_running is True

    # Stop monitoring
    await monitor.stop()
    assert monitor.is_running is False

    # Cancel the task
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(test_container_monitor_initialization())
    print("✅ Container monitoring tests passed!")
