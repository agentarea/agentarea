"""Logging configuration with workspace context support."""

import json
import logging
import logging.config
from typing import Any, cast

from ..auth.context import UserContext
from .filters import LogSanitizerFilter, WorkspaceContextFilter


class WorkspaceContextFormatter(logging.Formatter):
    """Custom formatter that includes workspace context in structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with workspace context."""
        # Create structured log entry
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add workspace context if available
        if hasattr(record, "user_id"):
            log_entry["user_id"] = cast(Any, record).user_id
        if hasattr(record, "workspace_id"):
            log_entry["workspace_id"] = cast(Any, record).workspace_id

        trace_ids = _current_trace_ids()
        if trace_ids:
            log_entry.update(trace_ids)

        # Add audit event data if present
        if hasattr(record, "audit_event"):
            log_entry["audit_event"] = cast(Any, record).audit_event

        # Add any extra fields
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
                "user_id",
                "workspace_id",
                "audit_event",
                "user_id_added",
            ]:
                if not key.startswith("_"):
                    log_entry[key] = value

        return json.dumps(log_entry, default=str)


def setup_logging(
    level: str = "INFO",
    enable_structured_logging: bool = True,
    enable_audit_logging: bool = True,
    user_context: UserContext | None = None,
) -> None:
    """Set up logging configuration with workspace context support.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        enable_structured_logging: Whether to use structured JSON logging
        enable_audit_logging: Whether to enable audit logging
        user_context: User context to include in logs
    """
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {"format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"},
            "structured": {
                "()": WorkspaceContextFormatter,
            },
        },
        "filters": {
            "workspace_context": {
                "()": WorkspaceContextFilter,
                "user_context": user_context,
            },
            "sanitize": {
                "()": LogSanitizerFilter,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "structured" if enable_structured_logging else "standard",
                "filters": (["workspace_context"] if user_context else []) + ["sanitize"],
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            "agentarea": {"level": level, "handlers": ["console"], "propagate": False},
            "agentarea.audit": {
                "level": "INFO" if enable_audit_logging else "WARNING",
                "handlers": ["console"],
                "propagate": False,
            },
        },
        "root": {"level": level, "handlers": ["console"]},
    }

    logging.config.dictConfig(config)


def _current_trace_ids() -> dict[str, str]:
    """Return current OpenTelemetry trace identifiers when available."""
    try:
        from opentelemetry import trace
    except ImportError:
        return {}

    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context.is_valid:
        return {}

    return {
        "trace_id": f"{span_context.trace_id:032x}",
        "span_id": f"{span_context.span_id:016x}",
    }


def update_logging_context(user_context: UserContext) -> None:
    """Update the workspace context for all existing loggers.

    Args:
        user_context: New user context to apply
    """
    # Update all workspace context filters
    for handler in logging.getLogger().handlers:
        for filter_obj in handler.filters:
            if isinstance(filter_obj, WorkspaceContextFilter):
                filter_obj.set_context(user_context)

    # Update filters in child loggers
    for logger_name in logging.Logger.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        for handler in logger.handlers:
            for filter_obj in handler.filters:
                if isinstance(filter_obj, WorkspaceContextFilter):
                    filter_obj.set_context(user_context)
