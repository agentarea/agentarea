"""FastAPI middleware to capture request context for audit events."""

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .context import AuditContext, audit_context


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Captures source IP, user-agent, and request ID into contextvars.

    Must be added before route handlers so audit events can read
    the request context via ``get_audit_context()``.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Use X-Forwarded-For behind reverse proxy, fall back to direct client
        forwarded = request.headers.get("x-forwarded-for")
        source_ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else None)
        )

        ctx = AuditContext(
            source_ip=source_ip,
            user_agent=request.headers.get("user-agent"),
            request_id=request.headers.get("x-request-id", str(uuid4())),
        )

        token = audit_context.set(ctx)
        try:
            return await call_next(request)
        finally:
            audit_context.reset(token)
