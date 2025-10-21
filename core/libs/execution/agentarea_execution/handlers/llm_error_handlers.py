"""Event handlers for LLM-related errors."""

import logging
from typing import Any

from agentarea_common.events.base_events import DomainEvent

logger = logging.getLogger(__name__)


class LLMErrorHandler:
    """Handles LLM-related error events."""

    def __init__(self):
        self.error_counts = {}
        self.auth_failures = {}

    async def handle_auth_failure(self, event: DomainEvent) -> None:
        """Handle LLM authentication failures."""
        try:
            data = event.data.get("original_data")
            if not data:
                raise ValueError("Missing original_data in DomainEvent")

            model_id = data["model_id"]  # Will raise KeyError if missing
            error_message = data["error"]  # Will raise KeyError if missing
            iteration = data.get("iteration", 0)  # iteration can have default
            task_id = event.data["aggregate_id"]  # Will raise KeyError if missing

            # Track authentication failures
            if model_id not in self.auth_failures:
                self.auth_failures[model_id] = []

            self.auth_failures[model_id].append(
                {
                    "timestamp": event.timestamp,
                    "error": error_message,
                    "iteration": iteration,
                    "task_id": task_id,
                }
            )

            logger.error(
                f"LLM Authentication failure for model {model_id} in task {task_id}: {error_message}"
            )

            # Could add additional actions here:
            # - Send notification to administrators
            # - Disable the model temporarily
            # - Switch to backup model
            # - Update model configuration

            # For now, just log the failure pattern
            failure_count = len(self.auth_failures[model_id])
            if failure_count >= 3:
                logger.critical(
                    f"Model {model_id} has failed authentication {failure_count} times. "
                    f"Consider checking API key configuration."
                )

        except Exception as e:
            logger.error(f"Error handling auth failure event: {e}")

    async def handle_rate_limit(self, event: DomainEvent) -> None:
        """Handle LLM rate limiting events."""
        try:
            data = event.data.get("original_data")
            if not data:
                raise ValueError("Missing original_data in DomainEvent")

            model_id = data["model_id"]  # Will raise KeyError if missing
            error_message = data["error"]  # Will raise KeyError if missing
            task_id = event.data["aggregate_id"]  # Will raise KeyError if missing

            logger.warning(
                f"LLM Rate limit exceeded for model {model_id} in task {task_id}: {error_message}"
            )

            # Could implement backoff strategies or model switching here

        except Exception as e:
            logger.error(f"Error handling rate limit event: {e}")

    async def handle_quota_exceeded(self, event: DomainEvent) -> None:
        """Handle LLM quota exceeded events."""
        try:
            data = event.data.get("original_data")
            if not data:
                raise ValueError("Missing original_data in DomainEvent")

            model_id = data["model_id"]  # Will raise KeyError if missing
            error_message = data["error"]  # Will raise KeyError if missing
            task_id = event.data["aggregate_id"]  # Will raise KeyError if missing

            logger.critical(
                f"LLM Quota exceeded for model {model_id} in task {task_id}: {error_message}"
            )

            # Could implement:
            # - Pause all tasks using this model
            # - Switch to backup model
            # - Send urgent notification to administrators

        except Exception as e:
            logger.error(f"Error handling quota exceeded event: {e}")

    async def handle_model_not_found(self, event: DomainEvent) -> None:
        """Handle model not found events."""
        try:
            data = event.data.get("original_data")
            if not data:
                raise ValueError("Missing original_data in DomainEvent")

            model_id = data["model_id"]  # Will raise KeyError if missing
            error_message = data["error"]  # Will raise KeyError if missing
            task_id = event.data["aggregate_id"]  # Will raise KeyError if missing

            logger.error(
                f"LLM Model not found: {model_id} in task {task_id}: {error_message}"
            )

            # Could implement:
            # - Mark model as unavailable
            # - Switch to backup model
            # - Update model configuration

        except Exception as e:
            logger.error(f"Error handling model not found event: {e}")

    def get_error_summary(self) -> dict[str, Any]:
        """Get summary of error patterns."""
        return {
            "auth_failures": {
                model_id: len(failures) for model_id, failures in self.auth_failures.items()
            },
            "total_auth_failures": sum(len(failures) for failures in self.auth_failures.values()),
        }


# Global instance for use across the application
llm_error_handler = LLMErrorHandler()


async def handle_llm_error_event(event: DomainEvent) -> None:
    """Route LLM error events to appropriate handlers."""
    # Try to get original_event_type, fallback to event_type (this fallback is reasonable)
    event_type = event.data.get("original_event_type")
    if not event_type:
        event_type = event.event_type
        logger.warning(
            f"Event missing original_event_type, using event_type: {event_type}"
        )

    if event_type == "LLMAuthFailed":
        await llm_error_handler.handle_auth_failure(event)
    elif event_type == "LLMRateLimited":
        await llm_error_handler.handle_rate_limit(event)
    elif event_type == "LLMQuotaExceeded":
        await llm_error_handler.handle_quota_exceeded(event)
    elif event_type == "LLMModelNotFound":
        await llm_error_handler.handle_model_not_found(event)
    else:
        logger.debug(f"Unhandled LLM error event type: {event_type}")
