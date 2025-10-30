"""Event streaming service for real-time event distribution.

This service is responsible for:
- Subscribing to events via FastStream broker (Redis, Kafka, RabbitMQ, etc.)
- Filtering events by task/aggregate
- Streaming events to consumers (SSE, WebSocket, etc.)

Broker-agnostic: Works with any FastStream-supported message broker.
This is NOT part of TaskService - it's a separate concern for event delivery.

ARCHITECTURE NOTE - Pattern Subscriptions and FastStream:
===========================================================
This service uses pattern-based subscriptions (e.g., "workflow.*") to subscribe to multiple
event channels via a single subscription. This is critical for event filtering architecture.

FastStream Framework Limitation:
- FastStream's @broker.subscriber() decorator API does NOT support pattern subscriptions
  for Redis Pub/Sub (only exact channel names are supported)
- Pattern subscriptions are only available for Redis Streams, not Pub/Sub
- See: https://docs.faststream.airt.dev/latest/redis/pub-sub/

Implementation Strategy:
- For wildcard patterns, we use FastStream's PubSub(pattern, pattern=True) helper class
- PubSub internally accesses broker._connection.psubscribe() to enable protocol-level
  pattern matching at the Redis level
- This is a pragmatic design decision: we accept the minor abstraction violation to
  maintain broker-agnostic code that works with all FastStream brokers

Trade-offs:
✓ Supports pattern subscriptions (critical feature)
✓ Broker-agnostic design (can migrate to Kafka/RabbitMQ without code changes)
✗ Uses internal FastStream APIs (_connection attribute)
✗ Relies on FastStream implementation details

Why Not Use Raw Redis Directly:
- Raw Redis connections create broker lock-in and prevent future migration to Kafka
- FastStream abstraction ensures proper message deserialization across all brokers
- Using PubSub() helper maintains compatibility with FastStream lifecycle

Future Consideration:
- If FastStream adds native pattern subscription support to the decorator API,
  this can be simplified without changing the interface
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Try to import FastStream Redis PubSub helper for pattern subscriptions
try:
    from faststream.redis import PubSub
except Exception:  # pragma: no cover - optional import
    PubSub = None


class EventStreamService:
    """Service for streaming real-time events from any FastStream broker.

    Broker-agnostic: Works with Redis, Kafka, RabbitMQ, NATS, and other FastStream brokers.
    """

    def __init__(self, broker: Any):
        """Initialize with a FastStream broker instance.

        Args:
            broker: FastStream broker instance (RedisBroker, KafkaBroker, etc.)
                   Should have a subscriber(channel) method that returns an async iterable
        """
        self.broker = broker

    async def stream_events_for_task(
        self,
        task_id: UUID,
        event_patterns: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events for a specific task in real-time.

        This is the main public method for consuming task events.
        Works with SSE, WebSocket, or any async consumer.

        Args:
            task_id: The task to stream events for
            event_patterns: Broker patterns to subscribe to (e.g., ["workflow.*"])
                          Defaults to all workflow events

        Yields:
            dict with keys: event_type, event_data, timestamp

        Example:
            async for event in event_stream.stream_events_for_task(task_id):
                print(f"Event: {event['event_type']}")
        """
        if event_patterns is None:
            event_patterns = ["workflow.*"]

        task_id_str = str(task_id)

        try:
            # Subscribe to all patterns and stream events
            async for event in self._subscribe_and_iterate(event_patterns, task_id_str):
                yield event

        except Exception as e:
            logger.error(f"EventStreamService error for task {task_id}: {e}", exc_info=True)
            raise

    async def stream_events(
        self,
        event_patterns: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream ALL events (no task filtering).

        Useful for monitoring, debugging, or application-wide event streaming.

        Args:
            event_patterns: Broker patterns to subscribe to
                          Defaults to all workflow events

        Yields:
            dict with keys: event_type, event_data, timestamp
        """
        if event_patterns is None:
            event_patterns = ["workflow.*"]

        try:
            async for event in self._subscribe_and_iterate(event_patterns):
                yield event

        except Exception as e:
            logger.error(f"EventStreamService error: {e}", exc_info=True)
            raise

    async def _subscribe_and_iterate(
        self,
        event_patterns: list[str],
        task_id_filter: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to patterns and iterate over messages using FastStream.

        FastStream's broker.subscriber() automatically handles:
        - Message deserialization (no manual UTF-8 decoding needed)
        - Broker-specific protocol unwrapping
        - Works with any FastStream-supported broker

        Args:
            event_patterns: Patterns to subscribe to
            task_id_filter: Optional task ID to filter events

        Yields:
            Parsed event dicts
        """
        # Ensure broker is connected if method exists
        if hasattr(self.broker, "connect"):
            try:
                await self.broker.connect()
            except Exception as e:
                # Connection may already be established; ignore failures
                logger.debug(f"Broker connection attempt ignored: {e}")

        for pattern in event_patterns:
            logger.info(
                f"EventStreamService: Subscribing to pattern '{pattern}'"
                f"{f' for task {task_id_filter}' if task_id_filter else ' for all events'}"
            )

            try:
                # Use FastStream dynamic subscribers with pattern support
                # IMPORTANT: Pattern subscriptions (e.g., "workflow.*") require special handling
                # in FastStream because the @broker.subscriber() decorator API does NOT support
                # pattern matching for Redis Pub/Sub - only exact channel names work.
                #
                # The PubSub(pattern, pattern=True) helper class enables protocol-level
                # pattern matching by internally using Redis's psubscribe() command.
                # This maintains the FastStream abstraction while enabling the pattern
                # filtering that our architecture requires.
                #
                # Design Decision:
                # - We use PubSub() instead of raw Redis to stay FastStream-compatible
                # - This allows future migration to Kafka/RabbitMQ without code changes
                # - The trade-off is accepting some reliance on FastStream internals
                channel = pattern
                if self._is_wildcard_pattern(pattern) and PubSub is not None:
                    channel = PubSub(pattern, pattern=True)

                # Use non-persistent dynamic subscriber and iterate messages
                subscriber = self.broker.subscriber(channel, persistent=False)

                # Start the subscriber
                await subscriber.start()

                try:
                    async for msg in subscriber:
                        try:
                            # Extract and decode message body
                            payload: Any = None
                            if hasattr(msg, "decoded_body") and msg.decoded_body is not None:
                                payload = msg.decoded_body
                            elif hasattr(msg, "body"):
                                payload = msg.body
                            else:
                                payload = msg  # fallback

                            # Normalize bytes/str payloads to dict
                            if isinstance(payload, bytes | bytearray):
                                try:
                                    payload = payload.decode("utf-8")
                                except Exception as e:
                                    logger.debug(f"Could not decode payload as UTF-8: {e}")
                            if isinstance(payload, str):
                                try:
                                    payload = json.loads(payload)
                                except Exception:
                                    # Keep as raw string if not JSON
                                    payload = {"data": payload}

                            # Parse and filter the message
                            event = self._parse_message(payload, task_id_filter, pattern)

                            if event:
                                yield event

                            # Manual acknowledgement per FastStream dynamic subscriber docs
                            if hasattr(msg, "ack"):
                                maybe_ack = msg.ack
                                if asyncio.iscoroutinefunction(maybe_ack):
                                    await maybe_ack()
                                else:
                                    try:
                                        maybe_ack()
                                    except Exception as e:
                                        logger.debug(f"Could not ack message: {e}")

                        except Exception as e:
                            logger.error(
                                f"Error processing message from pattern '{pattern}': {e}",
                                exc_info=True,
                            )
                            continue
                finally:
                    # Stop the subscriber
                    try:
                        await subscriber.stop()
                    except Exception as e:
                        logger.debug(f"Could not stop subscriber: {e}")

            except Exception as e:
                logger.error(f"Error subscribing to pattern '{pattern}': {e}", exc_info=True)
                # Continue to next pattern
                continue

    def _is_wildcard_pattern(self, pattern: str) -> bool:
        """Detect if a subscription pattern uses wildcard matching."""
        return "*" in pattern or "?" in pattern

    def _parse_message(
        self,
        message: Any,
        task_id_filter: str | None = None,
        channel: str | None = None,
    ) -> dict[str, Any] | None:
        """Parse a deserialized message into a structured event.

        At this point, FastStream has already handled:
        - Binary message format unwrapping
        - UTF-8 decoding
        - JSON deserialization

        We just need to:
        - Extract the event structure
        - Filter by task_id if provided

        Args:
            message: Deserialized message from FastStream (already JSON parsed)
            task_id_filter: If provided, only process events for this task
            channel: The channel/pattern this message came from

        Returns:
            Parsed event dict or None if filtered out
        """
        try:
            # Message body is already deserialized by FastStream
            # For most cases, it's the event_data dict
            if isinstance(message, dict):
                # Some FastStream Redis messages wrap the actual JSON as a string under 'data'
                if "data" in message and isinstance(message["data"], str):
                    try:
                        event_data = json.loads(message["data"])
                    except json.JSONDecodeError:
                        event_data = message
                else:
                    event_data = message
            else:
                # Fallback: convert to string if not already a dict
                event_data = {"data": str(message)}

            # Flatten DomainEvent nested 'data' if present: {'data': {'event_type': ..., 'data': {...}}}
            if (
                isinstance(event_data, dict)
                and isinstance(event_data.get("data"), dict)
                and isinstance(event_data["data"].get("data"), dict)
            ):
                event_data["data"] = event_data["data"]["data"]

            # Filter by task_id if provided
            # aggregate_id can be at different levels in the message structure:
            # 1. event_data["data"]["aggregate_id"] - typical structure
            # 2. event_data["aggregate_id"] - flattened structure
            if task_id_filter:
                # Try deep nested structure first
                aggregate_id = None
                if isinstance(event_data, dict):
                    if "data" in event_data and isinstance(event_data["data"], dict):
                        aggregate_id = event_data["data"].get("aggregate_id")
                    # Fallback to flattened form
                    if aggregate_id is None:
                        aggregate_id = event_data.get("aggregate_id")

                if aggregate_id and str(aggregate_id) != str(task_id_filter):
                    # Not for the requested task, skip
                    return None

            # Build response structure
            logger.debug(f"EventStreamService: parsed event_data={event_data}")
            return {
                "event_type": event_data.get("event_type")
                if isinstance(event_data, dict)
                else None,
                "event_data": event_data,
                "task_id": str(task_id_filter) if task_id_filter else None,
                "channel": channel,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to parse message from channel '{channel}': {e}", exc_info=True)
            return None
