"""Logging filters for workspace context."""

import logging
import re

from ..auth.context import UserContext

# Control characters that could forge log lines when logs are rendered as plain
# text: CR/LF and the other C0 control chars (keep tab \x09).
_CONTROL_CHARS = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]")


# Only structural patterns: each one matches a credential by the SHAPE of the
# string it sits in, never by a nearby identifier. A name-based rule
# ("secret: ...") cannot tell a value from a key — it redacts
# "Loaded secret: DATABASE_URL" and "password: None", destroying the diagnostic
# while protecting nothing. This codebase already learned that lesson with MCP
# env vars: trust the schema, not a regex over names.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Telegram bot tokens live in the URL path, so any httpx error quoting the
    # request URL carries the token with it.
    (re.compile(r"(/bot)\d+:[A-Za-z0-9_-]{20,}"), r"\1<redacted>"),
    # DSN credentials: scheme://user:secret@host
    (re.compile(r"(://[^:/\s@]+:)[^@/\s]+(@)"), r"\1<redacted>\2"),
    # Authorization headers.
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1<redacted>"),
    # Credentials carried in a URL query string.
    (
        re.compile(r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|password)=)[^&\s\"']+"),
        r"\1<redacted>",
    ),
)


# Attributes logging itself puts on a record; everything else came from extra=.
_STANDARD_RECORD_FIELDS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
        "asctime",
    }
)


def _redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class SecretRedactingFilter(logging.Filter):
    """Strip credentials out of log messages and rendered tracebacks.

    Secrets arrive in log strings incidentally — a token in a URL path, a
    password in a DSN, an SDK error quoting the request it failed on — so no
    amount of care at call sites covers it. Redacting in the pipeline does,
    including inside exception text, which the structured formatter renders.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # Never drop a record because redaction failed.
            return True

        redacted = _redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()

        # Pre-render the traceback so the secret is gone before the formatter
        # sees it; formatters reuse exc_text when it is already set.
        if record.exc_info and not record.exc_text:
            record.exc_text = _redact(logging.Formatter().formatException(record.exc_info))
        elif record.exc_text:
            record.exc_text = _redact(record.exc_text)

        # extra={} fields bypass the message entirely — the structured formatter
        # serializes each one verbatim, so a credential passed that way would
        # reach the log untouched.
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            if isinstance(value, str):
                cleaned = _redact(value)
                if cleaned != value:
                    record.__dict__[key] = cleaned

        return True


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
