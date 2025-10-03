"""Logging middleware for FastAPI to set workspace context."""

from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from ..auth.context import UserContext
from .config import update_logging_context
from .context_logger import get_context_logger


class LoggingContextMiddleware(BaseHTTPMiddleware):
    """Middleware to set workspace context for logging on each request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and set logging context.

        Args:
            request: The incoming request
            call_next: The next middleware/handler in the chain

        Returns:
            The response from the handler
        """
        # Try to get user context from request state
        user_context: UserContext = getattr(request.state, "user_context", None)

        if user_context:
            # Update logging context for this request
            update_logging_context(user_context)

            # Create a context logger for this request
            logger = get_context_logger("agentarea.request", user_context)

            # Log request start
            logger.info(
                f"{request.method} {request.url.path}",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": str(request.query_params),
                    "client_ip": request.client.host if request.client else None,
                },
            )

        try:
            # Process the request
            response = await call_next(request)

            if user_context:
                # Log successful response
                logger.info(
                    f"Response {response.status_code}",
                    extra={
                        "status_code": response.status_code,
                        "method": request.method,
                        "path": request.url.path,
                    },
                )

            return response

        except Exception as e:
            if user_context:
                # Log error response
                logger.error(
                    f"Request failed: {e!s}",
                    extra={
                        "error": str(e),
                        "method": request.method,
                        "path": request.url.path,
                        "exception_type": type(e).__name__,
                    },
                )
            raise
