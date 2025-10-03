#!/usr/bin/env python3
"""
Test EventBroker integration - reproducing the exact setup from worker and API.

This test verifies the full event publishing and subscription pipeline:
1. Publisher side (like workflow activities in worker)
2. Subscriber side (like SSE stream_task_events in API)
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from agentarea_common.config.broker import RedisSettings
from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.redis_event_broker import RedisEventBroker
from agentarea_common.events.router import create_event_broker_from_router, get_event_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_event_broker_setup():
    """Test the EventBroker setup exactly like the worker/API does."""
    logger.info("=== Testing EventBroker Setup ===")

    try:
        # Step 1: Create settings (like in worker/API)
        settings = RedisSettings()
        logger.info(f"Redis URL: {settings.REDIS_URL}")

        # Step 2: Create router (like in worker/API)
        router = get_event_router(settings)
        logger.info(f"Created router: {type(router).__name__}")
        logger.info(f"Router broker: {type(router.broker).__name__}")

        # Step 3: Create EventBroker from router (like in worker/API)
        event_broker = create_event_broker_from_router(router)
        logger.info(f"Created event broker: {type(event_broker).__name__}")
        logger.info(f"Event broker redis_broker: {type(event_broker.redis_broker).__name__}")

        # Step 4: Check if EventBroker has the right attributes
        logger.info(f"EventBroker attributes: {dir(event_broker)}")
        logger.info(f"RedisEventBroker.redis_broker attributes: {dir(event_broker.redis_broker)}")

        return event_broker

    except Exception as e:
        logger.error(f"❌ EventBroker setup failed: {e}")
        raise


async def test_event_publishing(event_broker: RedisEventBroker, task_id: UUID):
    """Test event publishing exactly like workflow activities do."""
    logger.info("=== Testing Event Publishing (like workflow activities) ===")

    try:
        # Create a test event exactly like the workflow does (with corrected DomainEvent structure)
        test_event = DomainEvent(
            event_id=str(uuid4()),
            event_type="workflow.LLMCallStarted",
            timestamp=datetime.now(UTC),
            # All other data goes into the data dict via kwargs
            aggregate_id=str(task_id),
            aggregate_type="task",
            original_event_type="LLMCallStarted",
            original_timestamp=datetime.now(UTC).isoformat(),
            original_data={
                "task_id": str(task_id),
                "agent_id": str(uuid4()),
                "execution_id": f"agent-task-{task_id}",
                "iteration": 1,
                "message_count": 2,
            },
        )

        logger.info(f"Created test event: {test_event.event_type}")
        logger.info(f"Event data keys: {list(test_event.data.keys())}")
        logger.info(f"Aggregate ID: {test_event.data.get('aggregate_id')}")

        # Try to publish (this is where the error occurs)
        logger.info("Attempting to publish...")
        await event_broker.publish(test_event)
        logger.info("✅ Successfully published event!")

        return True

    except Exception as e:
        logger.error(f"❌ Event publishing failed: {e}")
        logger.error(f"Error type: {type(e).__name__}")

        # Log detailed information about the event broker
        logger.error(f"EventBroker type: {type(event_broker)}")
        logger.error(f"EventBroker.redis_broker type: {type(event_broker.redis_broker)}")
        logger.error(
            f"Available methods on redis_broker: {[m for m in dir(event_broker.redis_broker) if not m.startswith('_')]}"
        )

        return False


async def test_event_subscription(event_broker: RedisEventBroker, task_id: UUID):
    """Test event subscription exactly like stream_task_events does."""
    logger.info("=== Testing Event Subscription (like stream_task_events) ===")

    try:
        # Set up subscription like stream_task_events does
        received_events = []
        subscription_task = None

        async def event_listener():
            """Listener function like in stream_task_events."""
            try:
                logger.info("Starting event listener...")

                # Access the underlying RedisBroker for subscription
                if hasattr(event_broker, "redis_broker"):
                    redis_broker = event_broker.redis_broker

                    # Check if it's connected
                    if not event_broker._connected:
                        await event_broker._ensure_connected()
                        logger.info("Redis broker connected")

                    # Try to access Redis connection for pubsub
                    connection_attrs = ["_connection", "connection", "client", "_client", "redis"]
                    redis_connection = None

                    for attr in connection_attrs:
                        if hasattr(redis_broker, attr):
                            redis_connection = getattr(redis_broker, attr)
                            logger.info(
                                f"Found Redis connection via '{attr}': {type(redis_connection)}"
                            )
                            break

                    if redis_connection:
                        # Create pubsub
                        pubsub = redis_connection.pubsub()
                        logger.info(f"Created pubsub: {type(pubsub)}")

                        # Subscribe to workflow patterns
                        await pubsub.psubscribe("workflow.*")
                        logger.info("Subscribed to workflow.* patterns")

                        # Listen for events (with timeout)
                        timeout_count = 0
                        max_timeout = 10  # Max 10 timeouts (30 seconds)

                        async for message in pubsub.listen():
                            if message["type"] == "pmessage":
                                try:
                                    # Debug the raw message data
                                    raw_data = message["data"]
                                    logger.info(f"Raw message data type: {type(raw_data)}")
                                    logger.info(f"Raw message data: {raw_data}")

                                    # Handle different data formats
                                    if isinstance(raw_data, (bytes, str)):
                                        if isinstance(raw_data, bytes):
                                            raw_data = raw_data.decode("utf-8")
                                        event_data = json.loads(raw_data)
                                    else:
                                        event_data = raw_data

                                    logger.info(f"Parsed event_data type: {type(event_data)}")
                                    logger.info(
                                        f"Parsed event_data keys: {list(event_data.keys()) if isinstance(event_data, dict) else 'not a dict'}"
                                    )

                                    # Handle FastStream message structure: {"data": "JSON_STRING", "headers": {...}}
                                    actual_event_data = event_data
                                    if (
                                        isinstance(event_data, dict)
                                        and "data" in event_data
                                        and isinstance(event_data["data"], str)
                                    ):
                                        # The actual event is a JSON string inside the "data" field
                                        try:
                                            actual_event_data = json.loads(event_data["data"])
                                            logger.info(
                                                f"Unwrapped inner event data: {actual_event_data}"
                                            )
                                        except json.JSONDecodeError as e:
                                            logger.warning(f"Failed to parse inner JSON: {e}")
                                            continue

                                    # Filter by task_id (check in the nested data structure)
                                    aggregate_id = actual_event_data.get("data", {}).get(
                                        "aggregate_id"
                                    )
                                    logger.info(
                                        f"Looking for aggregate_id: {aggregate_id}, task_id: {task_id!s}"
                                    )

                                    if aggregate_id == str(task_id):
                                        received_events.append(actual_event_data)
                                        logger.info(
                                            f"✅ Received filtered event for task {task_id}"
                                        )
                                        break  # Got our event, exit

                                except (json.JSONDecodeError, AttributeError) as e:
                                    logger.warning(f"Failed to decode/process event: {e}")
                                    logger.warning(f"Raw message: {message}")
                            elif message["type"] == "psubscribe":
                                logger.info(f"Subscribed to pattern: {message['pattern']}")
                            else:
                                timeout_count += 1
                                if timeout_count >= max_timeout:
                                    logger.warning("Timeout waiting for events")
                                    break

                        # Cleanup
                        await pubsub.punsubscribe("workflow.*")
                        await pubsub.close()
                        logger.info("Cleaned up pubsub connection")

                    else:
                        logger.error("Could not find Redis connection for pubsub")
                else:
                    logger.error("EventBroker doesn't have redis_broker attribute")

            except Exception as e:
                logger.error(f"Event listener error: {e}")

        # Start listener
        subscription_task = asyncio.create_task(event_listener())

        # Wait a bit for subscription to be ready
        await asyncio.sleep(1)

        # Now publish an event
        logger.info("Publishing test event for subscription...")
        await test_event_publishing(event_broker, task_id)

        # Wait for listener to process
        await asyncio.sleep(2)

        # Check results
        if subscription_task.done():
            await subscription_task  # Get any exceptions
        else:
            subscription_task.cancel()

        if received_events:
            logger.info(f"✅ Successfully received {len(received_events)} events via subscription")
            for event in received_events:
                event_type = event.get("event_type", "unknown")
                aggregate_id = event.get("data", {}).get("aggregate_id", "unknown")
                logger.info(f"  Event: {event_type} for task {aggregate_id}")
            return True
        else:
            logger.warning("⚠️  No events received via subscription")
            return False

    except Exception as e:
        logger.error(f"❌ Event subscription failed: {e}")
        if subscription_task and not subscription_task.done():
            subscription_task.cancel()
        return False


async def test_full_integration():
    """Test the full integration: setup, publish, subscribe."""
    logger.info("🚀 Starting Full EventBroker Integration Test")
    logger.info("=" * 60)

    task_id = uuid4()
    logger.info(f"Test task ID: {task_id}")

    try:
        # Step 1: Setup EventBroker
        event_broker = await test_event_broker_setup()

        # Step 2: Test publishing
        publish_success = await test_event_publishing(event_broker, task_id)

        # Step 3: Test subscription (includes publishing)
        subscribe_success = await test_event_subscription(event_broker, task_id)

        # Step 4: Cleanup
        if hasattr(event_broker, "_connected") and event_broker._connected:
            await event_broker.redis_broker.close()
            logger.info("Closed Redis connection")

        # Summary
        logger.info("=" * 60)
        logger.info("🏁 Integration Test Results:")
        logger.info("  Setup: ✅ SUCCESS")
        logger.info(f"  Publishing: {'✅ SUCCESS' if publish_success else '❌ FAILED'}")
        logger.info(f"  Subscription: {'✅ SUCCESS' if subscribe_success else '❌ FAILED'}")

        if publish_success and subscribe_success:
            logger.info("🎉 All integration tests PASSED!")
            return True
        else:
            logger.info("⚠️  Some integration tests FAILED - check the errors above")
            return False

    except Exception as e:
        logger.error(f"❌ Integration test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Run the full integration test
    result = asyncio.run(test_full_integration())
    exit(0 if result else 1)
