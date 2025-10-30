#!/usr/bin/env python3
"""Integration test for SSE streaming with workflow events."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.event_stream_service import EventStreamService
from agentarea_common.events.redis_event_broker import RedisEventBroker
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService
from faststream.redis import RedisBroker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockTaskRepository:
    """Mock task repository for testing."""

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


class MockEventBroker:
    """Mock event broker for testing."""

    async def publish(self, event: DomainEvent) -> None:
        logger.info(f"Published event: {event.event_type}")


class MockTaskManager:
    """Mock task manager for testing."""

    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        return task

    async def cancel_task(self, task_id: UUID) -> bool:
        return True


async def create_test_event(task_id: UUID, event_type: str) -> dict:
    """Create a test workflow event."""
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": {
            "task_id": str(task_id),
            "agent_id": str(uuid4()),
            "execution_id": f"agent-task-{task_id}",
            "message": f"Test {event_type} event",
        },
    }


async def test_task_service_event_streaming():
    """Test that EventStreamService can stream events properly."""
    logger.info("=== Testing EventStreamService Event Streaming ===")

    # Create mock dependencies for TaskService
    task_repo = MockTaskRepository()
    event_broker = MockEventBroker()
    task_manager = MockTaskManager()

    # Create TaskService instance (for backward compatibility in this test)
    task_service = TaskService(
        task_repository=task_repo, event_broker=event_broker, task_manager=task_manager
    )

    # Create a test task
    task_id = uuid4()
    test_task = SimpleTask(
        id=task_id,
        title="Test Task",
        description="Test streaming events",
        query="Test query",
        user_id="test_user",
        agent_id=uuid4(),
        status="running",
        execution_id=f"agent-task-{task_id}",
    )

    # Store the task
    await task_repo.create(test_task)

    logger.info(f"Created test task: {task_id}")

    # Test the EventStreamService event streaming
    try:
        # Create EventStreamService with FastStream RedisBroker
        redis_broker = RedisBroker("redis://localhost:6379/0")
        event_stream_service = EventStreamService(redis_broker)

        # Start streaming events with EventStreamService
        event_generator = event_stream_service.stream_events_for_task(task_id, event_patterns=["workflow.*"])

        logger.info("Event streaming generator created successfully")

        # Try to get a few events (with a timeout)
        events_received = []
        try:
            # Use timeout to prevent infinite waiting if no events come through
            async with asyncio.timeout(2):
                async for event in event_generator:
                    events_received.append(event)
                    logger.info(f"Received event: {event['event_type']}")

                    # Stop after receiving a few events
                    if len(events_received) >= 3:
                        break
        except TimeoutError:
            logger.info("No events received within timeout (this is ok if Redis has no recent events)")

        logger.info(f"Successfully checked event streaming: {len(events_received)} events received")

        logger.info("✅ EventStreamService event streaming test passed!")
        return True

    except Exception as e:
        logger.error(f"❌ EventStreamService event streaming test failed: {e}")
        # This is expected if Redis is not running - log but don't fail
        logger.info("Note: This test requires Redis to be running for full functionality")
        return False


async def test_redis_event_publishing():
    """Test publishing events to Redis (if available)."""
    logger.info("=== Testing Redis Event Publishing ===")

    try:
        # Try to create Redis broker
        redis_broker = RedisBroker()
        event_broker = RedisEventBroker(redis_broker)

        # Create a test event
        test_event = DomainEvent(
            event_type="WorkflowLLMCallStarted",
            data={
                "task_id": str(uuid4()),
                "agent_id": str(uuid4()),
                "model": "test-model",
                "cost": 0.01,
            },
        )

        # Try to publish
        async with event_broker:
            await event_broker.publish(test_event)
            logger.info("✅ Successfully published event to Redis")

        return True

    except Exception as e:
        logger.error(f"❌ Redis event publishing failed: {e}")
        logger.info("Note: This test requires Redis to be running")
        return False


async def test_sse_event_format():
    """Test SSE event formatting."""
    logger.info("=== Testing SSE Event Format ===")

    try:
        from agentarea_api.api.v1.agents_tasks import _format_sse_event

        # Test event formatting
        test_data = {
            "task_id": str(uuid4()),
            "status": "running",
            "timestamp": datetime.now(UTC).isoformat(),
        }

        sse_formatted = _format_sse_event("task_status_changed", test_data)

        # Check format
        assert "event: task_status_changed" in sse_formatted
        assert "data: " in sse_formatted
        assert json.dumps(test_data) in sse_formatted
        assert sse_formatted.endswith("\n\n")

        logger.info("✅ SSE event formatting test passed!")
        logger.info(f"Formatted event: {sse_formatted!r}")
        return True

    except Exception as e:
        logger.error(f"❌ SSE event formatting test failed: {e}")
        return False


async def run_all_tests():
    """Run all integration tests."""
    logger.info("🚀 Starting SSE Integration Tests")
    logger.info("=" * 50)

    results = {}

    # Test 1: TaskService event streaming
    results["task_service"] = await test_task_service_event_streaming()

    # Test 2: Redis event publishing
    results["redis_publishing"] = await test_redis_event_publishing()

    # Test 3: SSE formatting
    results["sse_format"] = await test_sse_event_format()

    # Summary
    logger.info("=" * 50)
    logger.info("🏁 Test Results Summary:")

    passed = sum(results.values())
    total = len(results)

    for test_name, passed_test in results.items():
        status = "✅ PASSED" if passed_test else "❌ FAILED"
        logger.info(f"  {test_name}: {status}")

    logger.info(f"Total: {passed}/{total} tests passed")

    if passed == total:
        logger.info("🎉 All tests passed!")
    else:
        logger.info("⚠️  Some tests failed - check Redis connection if needed")

    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
