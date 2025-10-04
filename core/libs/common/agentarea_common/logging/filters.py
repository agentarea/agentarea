"""Logging filters for workspace context."""

import logging

from ..auth.context import UserContext


class WorkspaceContextFilter(logging.Filter):
    """Logging filter that adds workspace context to log records."""

    def __init__(self, user_context: UserContext | None = None):
        """Initialize filter with user context.

        Args:
            user_context: User and workspace context to add to log records
        """
        super().__init__()
        self.user_context = user_context

    def filter(self, record: logging.LogRecord) -> bool:
        """Add workspace context to log record.

        Args:
            record: Log record to filter

        Returns:
            True to allow the record to be logged
        """
        if self.user_context:
            # Add workspace context to the log record
            record.user_id = self.user_context.user_id
            record.workspace_id = self.user_context.workspace_id

            # Also add to the message if not already present
            if not hasattr(record, "user_id_added"):
                record.msg = f"[workspace:{self.user_context.workspace_id}] [user:{self.user_context.user_id}] {record.msg}"
                record.user_id_added = True

        return True

    def set_context(self, user_context: UserContext) -> None:
        """Update the user context for this filter.

        Args:
            user_context: New user and workspace context
        """
        self.user_context = user_context
