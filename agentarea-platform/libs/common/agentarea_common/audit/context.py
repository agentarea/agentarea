"""Request-scoped audit context via contextvars."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditContext:
    """Request context captured by middleware for audit events."""

    source_ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


audit_context: ContextVar[AuditContext] = ContextVar("audit_context")


def get_audit_context() -> AuditContext:
    """Get the current request's audit context."""
    return audit_context.get(AuditContext())
