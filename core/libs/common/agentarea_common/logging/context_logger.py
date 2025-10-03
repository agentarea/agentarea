"""Context-aware logger that automatically includes workspace context."""

import logging
from typing import Any

from ..auth.context import UserContext


class ContextLogger:
    """Logger wrapper that automatically includes workspace context in log messages."""

    def __init__(self, logger: logging.Logger, user_context: UserContext | None = None):
        """Initialize context logger.

        Args:
            logger: The underlying logger to wrap
            user_context: User and workspace context to include in logs
        """
        self.logger = logger
        self.user_context = user_context

    def _get_extra_context(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Get extra context including workspace information.

        Args:
            extra: Additional extra context to include

        Returns:
            Combined extra context with workspace information
        """
        context = extra.copy() if extra else {}

        if self.user_context:
            context.update(
                {
                    "user_id": self.user_context.user_id,
                    "workspace_id": self.user_context.workspace_id,
                }
            )

        return context

    def debug(
        self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Log debug message with workspace context."""
        self.logger.debug(msg, *args, extra=self._get_extra_context(extra), **kwargs)

    def info(
        self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Log info message with workspace context."""
        self.logger.info(msg, *args, extra=self._get_extra_context(extra), **kwargs)

    def warning(
        self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Log warning message with workspace context."""
        self.logger.warning(msg, *args, extra=self._get_extra_context(extra), **kwargs)

    def error(
        self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Log error message with workspace context."""
        self.logger.error(msg, *args, extra=self._get_extra_context(extra), **kwargs)

    def critical(
        self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Log critical message with workspace context."""
        self.logger.critical(msg, *args, extra=self._get_extra_context(extra), **kwargs)

    def exception(
        self, msg: str, *args: Any, extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        """Log exception message with workspace context."""
        self.logger.exception(msg, *args, extra=self._get_extra_context(extra), **kwargs)

    def set_context(self, user_context: UserContext) -> None:
        """Update the user context for this logger.

        Args:
            user_context: New user and workspace context
        """
        self.user_context = user_context


def get_context_logger(name: str, user_context: UserContext | None = None) -> ContextLogger:
    """Get a context-aware logger.

    Args:
        name: Logger name
        user_context: User and workspace context

    Returns:
        Context-aware logger instance
    """
    logger = logging.getLogger(name)
    return ContextLogger(logger, user_context)
