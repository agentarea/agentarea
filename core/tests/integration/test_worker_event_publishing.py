#!/usr/bin/env python3
"""
Test worker event publishing activity fix.

This test verifies that the publish_workflow_events_activity can correctly
convert RedisRouter to RedisEventBroker for publishing events.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from agentarea_common.config.broker import RedisSettings
from agentarea_common.events.router import get_event_router
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_execution.activities.agent_execution_activities import make_agent_activities
from agentarea_execution.interfaces import ActivityDependencies

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockSecretManager(BaseSecretManager):
    """Mock secret manager for testing."""

    async def get_secret(self, key: str) -> str | None:
        return f"mock_secret_for_{key}"

    async def set_secret(self, key: str, value: str) -> None:
        pass  # Mock implementation


class MockSettings:
    """Mock settings for testing."""

    def __init__(self):
        self.broker = RedisSettings()


async def test_worker_event_publishing():
    """Test that the fixed activity can publish events through RedisRouter."""
    logger.info("🧪 Testing Worker Event Publishing Activity Fix")
    logger.info("=" * 50)

    try:
        # Create dependencies like the worker does
        settings = MockSettings()
        event_broker = get_event_router(settings.broker)  # This returns RedisRouter
        secret_manager = MockSecretManager()

        dependencies = ActivityDependencies(
            settings=settings,
            event_broker=event_broker,  # RedisRouter instance
            secret_manager=secret_manager,
        )

        logger.info(f"Event broker type: {type(dependencies.event_broker)}")
        logger.info(f"Has 'broker' attribute: {hasattr(dependencies.event_broker, 'broker')}")

        # Create activities using the factory (like worker does)
        activities = make_agent_activities(dependencies)

        # Find the publish_workflow_events_activity
        publish_activity = None
        for activity in activities:
            if hasattr(activity, "__name__") and "publish_workflow_events" in activity.__name__:
                publish_activity = activity
                break

        if not publish_activity:
            logger.error("❌ Could not find publish_workflow_events_activity")
            return False

        logger.info(f"✅ Found activity: {publish_activity.__name__}")

        # Create test event data (like workflow would pass)
        task_id = uuid4()
        test_events = [
            json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_type": "LLMCallStarted",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "task_id": str(task_id),
                        "agent_id": str(uuid4()),
                        "execution_id": f"agent-task-{task_id}",
                        "iteration": 1,
                        "model": "test-model",
                    },
                }
            ),
            json.dumps(
                {
                    "event_id": str(uuid4()),
                    "event_type": "LLMCallCompleted",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "data": {
                        "task_id": str(task_id),
                        "agent_id": str(uuid4()),
                        "execution_id": f"agent-task-{task_id}",
                        "iteration": 1,
                        "response": "Test response",
                    },
                }
            ),
        ]

        # Test the activity
        logger.info(f"📤 Testing activity with {len(test_events)} events...")
        result = await publish_activity(test_events)

        if result:
            logger.info("✅ SUCCESS: Activity executed without errors!")
            logger.info("Events were successfully published through RedisRouter → RedisEventBroker")
            return True
        else:
            logger.error("❌ FAILED: Activity returned False")
            return False

    except Exception as e:
        logger.error(f"❌ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_worker_event_publishing())
    logger.info("=" * 50)
    if result:
        logger.info("🎉 Worker Event Publishing Fix VERIFIED!")
        logger.info("The RedisRouter → RedisEventBroker conversion works correctly.")
    else:
        logger.info("❌ Worker Event Publishing Fix FAILED")
    exit(0 if result else 1)
