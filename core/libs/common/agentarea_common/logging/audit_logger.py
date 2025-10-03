"""Audit logging with workspace context for resource operations."""

import json
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from ..auth.context import UserContext


class AuditAction(Enum):
    """Audit action types."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    READ = "read"
    LIST = "list"
    ERROR = "error"


class AuditEvent:
    """Structured audit event with workspace context."""

    def __init__(
        self,
        action: AuditAction,
        resource_type: str,
        user_context: UserContext,
        resource_id: str | UUID | None = None,
        resource_data: dict[str, Any] | None = None,
        error: str | None = None,
        additional_context: dict[str, Any] | None = None,
    ):
        """Initialize audit event.

        Args:
            action: The action being performed
            resource_type: Type of resource (e.g., 'agent', 'task', 'trigger')
            user_context: Current user and workspace context
            resource_id: ID of the resource being acted upon
            resource_data: Resource data for create/update operations
            error: Error message for error events
            additional_context: Additional context information
        """
        self.timestamp = datetime.now(UTC)
        self.action = action
        self.resource_type = resource_type
        self.user_id = user_context.user_id
        self.workspace_id = user_context.workspace_id

        # Handle resource_id conversion safely to avoid async database queries
        if resource_id is None:
            self.resource_id = None
        elif hasattr(resource_id, "id") and hasattr(resource_id, "_sa_instance_state"):
            # For SQLAlchemy model objects, get the ID safely
            try:
                # Try to get the ID without triggering lazy loading
                state = resource_id._sa_instance_state
                if state.key is not None:
                    # Object is loaded, get the ID from the key
                    self.resource_id = str(state.key[1])
                else:
                    # Object is not loaded, use None to avoid triggering queries
                    self.resource_id = None
            except Exception:
                # If we can't get the ID safely, use None
                self.resource_id = None
        elif hasattr(resource_id, "id"):
            # For objects with id attribute but not SQLAlchemy models
            try:
                self.resource_id = str(resource_id.id)
            except Exception:
                self.resource_id = None
        else:
            # For other objects (str, UUID, etc.), try to convert to string
            try:
                self.resource_id = str(resource_id)
            except Exception:
                self.resource_id = None

        self.resource_data = resource_data or {}
        self.error = error
        self.additional_context = additional_context or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert audit event to dictionary for logging."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "resource_type": self.resource_type,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "resource_id": self.resource_id,
            "resource_data": self.resource_data,
            "error": self.error,
            "additional_context": self.additional_context,
        }

    def to_json(self) -> str:
        """Convert audit event to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class AuditLogger:
    """Audit logger with workspace context support."""

    def __init__(self, logger_name: str = "agentarea.audit"):
        """Initialize audit logger.

        Args:
            logger_name: Name of the logger to use
        """
        self.logger = logging.getLogger(logger_name)

        # Ensure audit logger has appropriate level
        if not self.logger.handlers:
            # Add a handler if none exists
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_event(self, event: AuditEvent) -> None:
        """Log an audit event.

        Args:
            event: The audit event to log
        """
        # Log as structured JSON for easy parsing
        self.logger.info(
            f"AUDIT: {event.action.value.upper()} {event.resource_type}",
            extra={
                "audit_event": event.to_dict(),
                "user_id": event.user_id,
                "workspace_id": event.workspace_id,
                "resource_type": event.resource_type,
                "action": event.action.value,
            },
        )

    def log_create(
        self,
        resource_type: str,
        user_context: UserContext,
        resource_id: str | UUID,
        resource_data: dict[str, Any] | None = None,
        **additional_context: Any,
    ) -> None:
        """Log resource creation.

        Args:
            resource_type: Type of resource created
            user_context: Current user and workspace context
            resource_id: ID of the created resource
            resource_data: Data of the created resource
            **additional_context: Additional context information
        """
        event = AuditEvent(
            action=AuditAction.CREATE,
            resource_type=resource_type,
            user_context=user_context,
            resource_id=resource_id,
            resource_data=resource_data,
            additional_context=additional_context,
        )
        self.log_event(event)

    def log_update(
        self,
        resource_type: str,
        user_context: UserContext,
        resource_id: str | UUID,
        resource_data: dict[str, Any] | None = None,
        **additional_context: Any,
    ) -> None:
        """Log resource update.

        Args:
            resource_type: Type of resource updated
            user_context: Current user and workspace context
            resource_id: ID of the updated resource
            resource_data: Updated data
            **additional_context: Additional context information
        """
        event = AuditEvent(
            action=AuditAction.UPDATE,
            resource_type=resource_type,
            user_context=user_context,
            resource_id=resource_id,
            resource_data=resource_data,
            additional_context=additional_context,
        )
        self.log_event(event)

    def log_delete(
        self,
        resource_type: str,
        user_context: UserContext,
        resource_id: str | UUID,
        **additional_context: Any,
    ) -> None:
        """Log resource deletion.

        Args:
            resource_type: Type of resource deleted
            user_context: Current user and workspace context
            resource_id: ID of the deleted resource
            **additional_context: Additional context information
        """
        event = AuditEvent(
            action=AuditAction.DELETE,
            resource_type=resource_type,
            user_context=user_context,
            resource_id=resource_id,
            additional_context=additional_context,
        )
        self.log_event(event)

    def log_read(
        self,
        resource_type: str,
        user_context: UserContext,
        resource_id: str | UUID | None = None,
        **additional_context: Any,
    ) -> None:
        """Log resource read access.

        Args:
            resource_type: Type of resource accessed
            user_context: Current user and workspace context
            resource_id: ID of the accessed resource (if specific resource)
            **additional_context: Additional context information
        """
        event = AuditEvent(
            action=AuditAction.READ,
            resource_type=resource_type,
            user_context=user_context,
            resource_id=resource_id,
            additional_context=additional_context,
        )
        self.log_event(event)

    def log_list(
        self,
        resource_type: str,
        user_context: UserContext,
        count: int | None = None,
        filters: dict[str, Any] | None = None,
        **additional_context: Any,
    ) -> None:
        """Log resource list access.

        Args:
            resource_type: Type of resources listed
            user_context: Current user and workspace context
            count: Number of resources returned
            filters: Filters applied to the list
            **additional_context: Additional context information
        """
        context = additional_context.copy()
        if count is not None:
            context["count"] = count
        if filters:
            context["filters"] = filters

        event = AuditEvent(
            action=AuditAction.LIST,
            resource_type=resource_type,
            user_context=user_context,
            additional_context=context,
        )
        self.log_event(event)

    def log_error(
        self,
        resource_type: str,
        user_context: UserContext,
        error: str,
        resource_id: str | UUID | None = None,
        **additional_context: Any,
    ) -> None:
        """Log error with workspace context.

        Args:
            resource_type: Type of resource involved in error
            user_context: Current user and workspace context
            error: Error message
            resource_id: ID of the resource involved (if applicable)
            **additional_context: Additional context information
        """
        event = AuditEvent(
            action=AuditAction.ERROR,
            resource_type=resource_type,
            user_context=user_context,
            resource_id=resource_id,
            error=error,
            additional_context=additional_context,
        )
        self.log_event(event)


# Global audit logger instance
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    """Get the global audit logger instance."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
