"""Logging utilities for the trigger system.

This module provides structured logging with correlation IDs and consistent
error handling patterns for all trigger operations.
"""

import logging
import uuid
from contextvars import ContextVar
from typing import Any
from uuid import UUID

# Context variable to store correlation ID across async operations
correlation_id_context: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class TriggerLogger:
    """Enhanced logger for trigger operations with correlation ID support."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)

    def _get_correlation_id(self) -> str:
        """Get or generate correlation ID for current operation."""
        correlation_id = correlation_id_context.get()
        if not correlation_id:
            correlation_id = str(uuid.uuid4())[:8]  # Short correlation ID
            correlation_id_context.set(correlation_id)
        return correlation_id

    def _format_message(self, message: str, **kwargs) -> str:
        """Format log message with correlation ID and additional context."""
        correlation_id = self._get_correlation_id()
        context_parts = [f"correlation_id={correlation_id}"]

        # Add trigger_id if provided
        if "trigger_id" in kwargs:
            context_parts.append(f"trigger_id={kwargs['trigger_id']}")

        # Add execution_id if provided
        if "execution_id" in kwargs:
            context_parts.append(f"execution_id={kwargs['execution_id']}")

        # Add webhook_id if provided
        if "webhook_id" in kwargs:
            context_parts.append(f"webhook_id={kwargs['webhook_id']}")

        # Add task_id if provided
        if "task_id" in kwargs:
            context_parts.append(f"task_id={kwargs['task_id']}")

        context_str = " | ".join(context_parts)
        return f"[{context_str}] {message}"

    def info(self, message: str, **kwargs):
        """Log info message with correlation context."""
        formatted_message = self._format_message(message, **kwargs)
        self.logger.info(formatted_message)

    def warning(self, message: str, **kwargs):
        """Log warning message with correlation context."""
        formatted_message = self._format_message(message, **kwargs)
        self.logger.warning(formatted_message)

    def error(self, message: str, **kwargs):
        """Log error message with correlation context."""
        formatted_message = self._format_message(message, **kwargs)
        self.logger.error(formatted_message)

    def debug(self, message: str, **kwargs):
        """Log debug message with correlation context."""
        formatted_message = self._format_message(message, **kwargs)
        self.logger.debug(formatted_message)


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID for current operation context."""
    correlation_id_context.set(correlation_id)


def get_correlation_id() -> str | None:
    """Get current correlation ID."""
    return correlation_id_context.get()


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())[:8]


class TriggerError(Exception):
    """Base exception for trigger system errors."""

    def __init__(self, message: str, correlation_id: str | None = None, **context):
        self.correlation_id = correlation_id or get_correlation_id()
        self.context = context
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for structured logging."""
        return {
            "error_type": self.__class__.__name__,
            "message": str(self),
            "correlation_id": self.correlation_id,
            "context": self.context,
        }


class TriggerValidationError(TriggerError):
    """Raised when trigger validation fails."""

    pass


class TriggerNotFoundError(TriggerError):
    """Raised when a trigger is not found."""

    pass


class TriggerExecutionError(TriggerError):
    """Raised when trigger execution fails."""

    pass


class WebhookValidationError(TriggerError):
    """Raised when webhook validation fails."""

    pass


class DependencyUnavailableError(TriggerError):
    """Raised when required dependencies are not available."""

    pass


class TriggerTimeoutError(TriggerError):
    """Raised when trigger operation times out."""

    pass


def log_trigger_operation(operation: str, trigger_id: UUID | None = None, **context):
    """Decorator to log trigger operations with error handling."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            logger = TriggerLogger(func.__module__)
            correlation_id = generate_correlation_id()
            set_correlation_id(correlation_id)

            log_context = {"operation": operation, "correlation_id": correlation_id, **context}

            if trigger_id:
                log_context["trigger_id"] = trigger_id

            try:
                logger.info(f"Starting {operation}", **log_context)
                result = await func(*args, **kwargs)
                logger.info(f"Completed {operation}", **log_context)
                return result
            except Exception as e:
                error_context = {**log_context, "error": str(e)}
                logger.error(f"Failed {operation}: {e}", **error_context)
                raise

        return wrapper

    return decorator
