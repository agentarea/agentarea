"""Logging configuration with workspace context support."""

import json
import logging
import logging.config
from typing import Any

from ..auth.context import UserContext
from .filters import WorkspaceContextFilter


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
            log_entry["user_id"] = record.user_id
        if hasattr(record, "workspace_id"):
            log_entry["workspace_id"] = record.workspace_id

        # Add audit event data if present
        if hasattr(record, "audit_event"):
            log_entry["audit_event"] = record.audit_event

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
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "structured" if enable_structured_logging else "standard",
                "filters": ["workspace_context"] if user_context else [],
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

    # Add audit file handler if audit logging is enabled
    if enable_audit_logging:
        config["handlers"]["audit_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "structured",
            "filename": "audit.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "filters": ["workspace_context"] if user_context else [],
        }
        config["loggers"]["agentarea.audit"]["handlers"].append("audit_file")

    logging.config.dictConfig(config)


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
