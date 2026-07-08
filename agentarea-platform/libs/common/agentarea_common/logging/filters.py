"""Logging filters for workspace context."""

import logging
import re

from ..auth.context import UserContext

# Control characters that could forge log lines when logs are rendered as plain
# text: CR/LF and the other C0 control chars (keep tab \x09).
_CONTROL_CHARS = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")


class LogSanitizerFilter(logging.Filter):
    """Strip CR/LF and control characters from the rendered log message.

    Prevents log-forging: untrusted values (user ids, provider keys, queries)
    reach log calls throughout the codebase, and an embedded newline could
    otherwise inject a fake log line. Structured JSON output already escapes
    these, so this is defense-in-depth for any plain-text handler.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # Never drop a record because sanitization failed.
            return True

        sanitized = _CONTROL_CHARS.sub(" ", message)
        if sanitized != message:
            # getMessage() already applied args; collapse to the sanitized text.
            record.msg = sanitized
            record.args = ()

        return True


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
                record.msg = (
                    f"[workspace:{self.user_context.workspace_id}] "
                    f"[user:{self.user_context.user_id}] {record.msg}"
                )
                record.user_id_added = True

        return True

    def set_context(self, user_context: UserContext) -> None:
        """Update the user context for this filter.

        Args:
            user_context: New user and workspace context
        """
        self.user_context = user_context
