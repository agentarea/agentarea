"""Event publisher utilities for activities."""

import logging
from datetime import datetime
from uuid import uuid4

from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.router import create_event_broker_from_router

logger = logging.getLogger(__name__)


def create_event_publisher(event_broker, task_id: str):
    """Create an event publisher function for chunk events."""

    async def publish_chunk_event(chunk: str, chunk_index: int, is_final: bool = False):
        """Publish LLM chunk event."""
        try:
            redis_event_broker = create_event_broker_from_router(event_broker)

            chunk_event = {
                "event_type": "LLMCallChunk",
                "event_id": str(uuid4()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": {
                    "task_id": task_id,
                    "chunk": chunk,
                    "chunk_index": chunk_index,
                    "is_final": is_final,
                },
            }

            # Create proper domain event
            domain_event = DomainEvent(
                event_id=chunk_event["event_id"],
                event_type=f"workflow.{chunk_event['event_type']}",
                timestamp=datetime.fromisoformat(chunk_event["timestamp"].replace("Z", "+00:00")),
                aggregate_id=task_id,
                aggregate_type="task",
                original_event_type=chunk_event["event_type"],
                original_timestamp=chunk_event["timestamp"],
                original_data=chunk_event["data"],
            )

            # Publish via RedisEventBroker for real-time SSE
            await redis_event_broker.publish(domain_event)
            logger.debug(f"Published LLM chunk event {chunk_index} for task {task_id}")

        except Exception as e:
            logger.error(f"Failed to publish chunk event: {e}")

    return publish_chunk_event


async def publish_enriched_llm_error_event(
    error: Exception,
    task_id: str,
    agent_id: str,
    execution_id: str,
    model_id: str,
    provider_type: str | None,
    event_broker,
):
    """Publish enriched LLM error event with detailed error information."""
    try:
        redis_event_broker = create_event_broker_from_router(event_broker)

        error_type = type(error).__name__
        error_message = str(error)

        # Analyze error type and extract details
        error_data = {
            "task_id": task_id,
            "agent_id": agent_id,
            "execution_id": execution_id,
            "error": error_message,
            "error_type": error_type,
            "model_id": model_id,
            "provider_type": provider_type,
            "is_auth_error": _is_auth_error(error),
            "is_rate_limit_error": _is_rate_limit_error(error),
            "is_quota_error": _is_quota_error(error),
            "is_model_error": _is_model_error(error),
            "is_network_error": _is_network_error(error),
            "retryable": not _is_non_retryable_error(error),
        }

        # Add specific error details based on type
        if error_data["is_rate_limit_error"]:
            error_data["retry_after"] = _extract_retry_after(error)

        if error_data["is_quota_error"]:
            error_data["quota_type"] = _extract_quota_type(error)

        if error_data["is_network_error"]:
            error_data["status_code"] = _extract_status_code(error)

        error_event = {
            "event_type": "LLMCallFailed",
            "event_id": str(uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": error_data,
        }

        # Create proper domain event
        domain_event = DomainEvent(
            event_id=error_event["event_id"],
            event_type=f"workflow.{error_event['event_type']}",
            timestamp=datetime.fromisoformat(error_event["timestamp"].replace("Z", "+00:00")),
            aggregate_id=task_id,
            aggregate_type="task",
            original_event_type=error_event["event_type"],
            original_timestamp=error_event["timestamp"],
            original_data=error_event["data"],
        )

        # Publish via RedisEventBroker for real-time SSE
        await redis_event_broker.publish(domain_event)
        logger.info(f"Published enriched LLM error event for task {task_id}: {error_type}")

    except Exception as e:
        logger.error(f"Failed to publish enriched LLM error event: {e}")


def _is_auth_error(error: Exception) -> bool:
    """Check if error is authentication-related."""
    error_str = str(error).lower()
    error_type = type(error).__name__
    return (
        "authenticationerror" in error_type.lower()
        or "api_key" in error_str
        or "authentication" in error_str
        or "unauthorized" in error_str
        or "401" in error_str
    )


def _is_rate_limit_error(error: Exception) -> bool:
    """Check if error is rate limiting-related."""
    error_str = str(error).lower()
    error_type = type(error).__name__
    return (
        "ratelimiterror" in error_type.lower()
        or "rate limit" in error_str
        or "too many requests" in error_str
        or "429" in error_str
    )


def _is_quota_error(error: Exception) -> bool:
    """Check if error is quota/billing-related."""
    error_str = str(error).lower()
    return (
        "quota" in error_str
        or "billing" in error_str
        or "exceeded" in error_str
        or "insufficient funds" in error_str
    )


def _is_model_error(error: Exception) -> bool:
    """Check if error is model-related."""
    error_str = str(error).lower()
    return "model" in error_str and (
        "not found" in error_str or "does not exist" in error_str or "invalid" in error_str
    )


def _is_network_error(error: Exception) -> bool:
    """Check if error is network-related."""
    error_str = str(error).lower()
    error_type = type(error).__name__
    return (
        "connectionerror" in error_type.lower()
        or "timeouterror" in error_type.lower()
        or "network" in error_str
        or "connection" in error_str
        or "timeout" in error_str
    )


def _is_non_retryable_error(error: Exception) -> bool:
    """Determine if error should not be retried."""
    return _is_auth_error(error) or _is_quota_error(error) or _is_model_error(error)


def _extract_retry_after(error: Exception) -> int | None:
    """Extract retry-after header from rate limit errors."""
    error_str = str(error)
    # Simple pattern matching - could be enhanced
    import re

    match = re.search(r"retry.*?(\d+)", error_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _extract_quota_type(error: Exception) -> str | None:
    """Extract quota type from quota errors."""
    error_str = str(error).lower()
    if "monthly" in error_str:
        return "monthly"
    elif "daily" in error_str:
        return "daily"
    elif "token" in error_str:
        return "tokens"
    return None


def _extract_status_code(error: Exception) -> int | None:
    """Extract HTTP status code from network errors."""
    error_str = str(error)
    import re

    match = re.search(r"(\d{3})", error_str)
    if match:
        return int(match.group(1))
    return None
