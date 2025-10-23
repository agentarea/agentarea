#!/usr/bin/env python3
"""
End-to-end test for SSE workflow event streaming.

This test simulates the complete flow:
1. Workflow activity publishes events to Redis via EventBroker
2. SSE endpoint streams events to client via TaskService.stream_task_events
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentarea_common.config.broker import RedisSettings
from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.event_stream_service import EventStreamService
from agentarea_common.events.router import create_event_broker_from_router, get_event_router
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService
from faststream.redis import RedisBroker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockTaskRepository:
    """Mock repository for testing."""

    def __init__(self):
        self.tasks = {}

    async def get(self, task_id: UUID) -> SimpleTask | None:
        return self.tasks.get(task_id)

    async def create(self, task: SimpleTask) -> SimpleTask:
        self.tasks[task.id] = task
        return task

    async def update(self, task: SimpleTask) -> SimpleTask:
        self.tasks[task.id] = task
        return task

    async def list_tasks(self, **kwargs) -> list[SimpleTask]:
        return list(self.tasks.values())


class MockTaskManager:
    """Mock task manager for testing."""

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        return task

    async def cancel_task(self, task_id: UUID) -> bool:
        return True


async def simulate_workflow_publishing(event_broker, task_id: UUID, num_events: int = 3):
    """Simulate workflow activities publishing events."""
    logger.info(f"📤 Publishing {num_events} workflow events for task {task_id}")

    event_types = ["LLMCallStarted", "ToolExecutionStarted", "LLMCallCompleted"]

    for i in range(num_events):
        event_type = event_types[i % len(event_types)]

        # Create event exactly like workflow activities do
        workflow_event = DomainEvent(
            event_id=str(uuid4()),
            event_type=f"workflow.{event_type}",
            timestamp=datetime.now(UTC),
            aggregate_id=str(task_id),
            aggregate_type="task",
            original_event_type=event_type,
            original_timestamp=datetime.now(UTC).isoformat(),
            original_data={
                "task_id": str(task_id),
                "agent_id": str(uuid4()),
                "execution_id": f"agent-task-{task_id}",
                "iteration": i + 1,
                "message": f"Workflow {event_type} event #{i + 1}",
            },
        )

        # Publish via EventBroker (like workflow activities)
        await event_broker.publish(workflow_event)
        logger.info(f"  Published: {event_type} (event #{i + 1})")

        # Small delay between events
        await asyncio.sleep(0.1)


async def simulate_sse_consumption(event_stream_service: EventStreamService, task_id: UUID, max_events: int = 5):
    """Simulate SSE endpoint consuming events."""
    logger.info(f"📥 Starting SSE event consumption for task {task_id}")

    events_received = []

    try:
        # Stream events like SSE endpoint does
        async for event in event_stream_service.stream_events_for_task(task_id, event_patterns=["workflow.*"]):
            events_received.append(event)

            event_type = event.get("event_type", "unknown")
            event_data = event.get("data", {})
            logger.info(f"  Received: {event_type} - {event_data.get('message', 'no message')}")

            # Stop after receiving enough events or heartbeat
            if len(events_received) >= max_events or event_type == "heartbeat":
                break

    except Exception as e:
        logger.error(f"Error in SSE consumption: {e}")

    return events_received


async def test_end_to_end_workflow():
    """Test complete end-to-end workflow event streaming."""
    logger.info("🚀 Starting End-to-End Workflow Event Streaming Test")
    logger.info("=" * 60)

    # Setup
    task_id = uuid4()
    logger.info(f"Test Task ID: {task_id}")

    # Create EventBroker (like worker setup)
    settings = RedisSettings()
    router = get_event_router(settings)
    event_broker = create_event_broker_from_router(router)

    # Create TaskService (like API setup)
    task_repository = MockTaskRepository()
    task_manager = MockTaskManager()
    task_service = TaskService(
        task_repository=task_repository, event_broker=event_broker, task_manager=task_manager
    )

    # Create EventStreamService for event streaming
    redis_broker = RedisBroker("redis://localhost:6379/0")
    event_stream_service = EventStreamService(redis_broker)

    # Create and store test task
    test_task = SimpleTask(
        id=task_id,
        title="End-to-End Test Task",
        description="Testing workflow event streaming",
        query="Test SSE streaming",
        user_id="test_user",
        agent_id=uuid4(),
        status="running",
        execution_id=f"agent-task-{task_id}",
    )
    await task_repository.create(test_task)

    try:
        # Start SSE consumption in background
        logger.info("🔄 Starting concurrent workflow publishing and SSE consumption...")

        # Create consumption task
        consumption_task = asyncio.create_task(
            simulate_sse_consumption(event_stream_service, task_id, max_events=4)
        )

        # Small delay to let subscription set up
        await asyncio.sleep(1)

        # Start publishing events
        publishing_task = asyncio.create_task(
            simulate_workflow_publishing(event_broker, task_id, num_events=3)
        )

        # Wait for both to complete
        events_received, _ = await asyncio.gather(consumption_task, publishing_task)

        # Analyze results
        logger.info("=" * 60)
        logger.info("📊 End-to-End Test Results:")

        workflow_events = [
            e
            for e in events_received
            if not e.get("event_type", "").startswith("task_")
            and e.get("event_type") != "heartbeat"
        ]
        heartbeat_events = [e for e in events_received if e.get("event_type") == "heartbeat"]

        logger.info(f"  Total events received: {len(events_received)}")
        logger.info(f"  Workflow events: {len(workflow_events)}")
        logger.info(f"  Heartbeat events: {len(heartbeat_events)}")

        # Verify we received workflow events
        if workflow_events:
            logger.info("✅ SUCCESS: Received workflow events via SSE!")
            for event in workflow_events:
                event_type = event.get("event_type", "unknown").replace("workflow.", "")
                message = (
                    event.get("data", {}).get("original_data", {}).get("message", "no message")
                )
                logger.info(f"    - {event_type}: {message}")
            return True
        else:
            logger.warning("⚠️  No workflow events received (only heartbeats)")
            return False

    except Exception as e:
        logger.error(f"❌ End-to-end test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if hasattr(event_broker, "_connected") and event_broker._connected:
            await event_broker.redis_broker.close()
            logger.info("🧹 Cleaned up Redis connection")


if __name__ == "__main__":
    result = asyncio.run(test_end_to_end_workflow())
    logger.info("=" * 60)
    if result:
        logger.info("🎉 End-to-End Test PASSED! Workflow → Redis → SSE streaming works!")
    else:
        logger.info("❌ End-to-End Test FAILED - check the logs above")
    exit(0 if result else 1)
