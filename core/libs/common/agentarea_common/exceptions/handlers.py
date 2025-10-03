"""Error handlers for workspace-related exceptions."""

import logging
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse

from ..auth.context_manager import ContextManager
from .workspace import (
    InvalidJWTToken,
    MissingWorkspaceContext,
    WorkspaceAccessDenied,
    WorkspaceError,
    WorkspaceResourceNotFound,
)

logger = logging.getLogger(__name__)


def _get_workspace_context_for_logging() -> dict[str, Any]:
    """Get current workspace context for logging.

    Returns:
        Dict containing workspace context information
    """
    try:
        context = ContextManager.get_context()
        if context:
            return {
                "workspace_id": context.workspace_id,
                "user_id": context.user_id,
                "roles": context.roles,
            }
    except Exception:  # noqa: S110
        # If context is not available, return empty dict
        pass

    return {}


def _log_workspace_error(exc: WorkspaceError, request: Request) -> None:
    """Log workspace error with context information.

    Args:
        exc: The workspace exception
        request: FastAPI request object
    """
    # Get workspace context for logging
    context = _get_workspace_context_for_logging()

    # Build log context
    log_context = {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "request_method": request.method,
        "request_url": str(request.url),
        "request_path": request.url.path,
        **context,
    }

    # Add exception-specific context
    if hasattr(exc, "resource_type"):
        log_context["resource_type"] = exc.resource_type
    if hasattr(exc, "resource_id"):
        log_context["resource_id"] = exc.resource_id
    if hasattr(exc, "missing_field"):
        log_context["missing_field"] = exc.missing_field
    if hasattr(exc, "reason"):
        log_context["jwt_error_reason"] = exc.reason

    # Log at appropriate level based on exception type
    if isinstance(exc, WorkspaceAccessDenied | WorkspaceResourceNotFound):
        # These are expected security-related errors, log at INFO level
        logger.info("Workspace access violation", extra=log_context)
    elif isinstance(exc, MissingWorkspaceContext):
        # Missing context is a client error, log at WARNING level
        logger.warning("Missing workspace context", extra=log_context)
    elif isinstance(exc, InvalidJWTToken):
        # JWT errors are authentication issues, log at WARNING level
        logger.warning("JWT token validation failed", extra=log_context)
    else:
        # Other workspace errors are unexpected, log at ERROR level
        logger.error("Workspace error occurred", extra=log_context)


async def workspace_access_denied_handler(
    request: Request, exc: WorkspaceAccessDenied
) -> JSONResponse:
    """Handle workspace access denied errors.

    Returns 404 instead of 403 to avoid information leakage about
    resource existence in other workspaces.

    Args:
        request: FastAPI request object
        exc: WorkspaceAccessDenied exception

    Returns:
        JSONResponse with 404 status and generic error message
    """
    _log_workspace_error(exc, request)

    # Return 404 to avoid leaking information about resource existence
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "Resource not found",
            "detail": "The requested resource does not exist or you don't have access to it",
            "error_code": "RESOURCE_NOT_FOUND",
        },
        headers=_get_workspace_headers(),
    )


async def workspace_resource_not_found_handler(
    request: Request, exc: WorkspaceResourceNotFound
) -> JSONResponse:
    """Handle workspace resource not found errors.

    Args:
        request: FastAPI request object
        exc: WorkspaceResourceNotFound exception

    Returns:
        JSONResponse with 404 status
    """
    _log_workspace_error(exc, request)

    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "Resource not found",
            "detail": f"The requested {exc.resource_type} does not exist",
            "error_code": "RESOURCE_NOT_FOUND",
        },
        headers=_get_workspace_headers(),
    )


async def missing_workspace_context_handler(
    request: Request, exc: MissingWorkspaceContext
) -> JSONResponse:
    """Handle missing workspace context errors.

    Args:
        request: FastAPI request object
        exc: MissingWorkspaceContext exception

    Returns:
        JSONResponse with 400 status
    """
    _log_workspace_error(exc, request)

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Missing workspace context",
            "detail": f"Request must include valid {exc.missing_field} information",
            "error_code": "MISSING_CONTEXT",
        },
        headers=_get_workspace_headers(),
    )


async def invalid_jwt_token_handler(request: Request, exc: InvalidJWTToken) -> JSONResponse:
    """Handle invalid JWT token errors.

    Args:
        request: FastAPI request object
        exc: InvalidJWTToken exception

    Returns:
        JSONResponse with 401 status
    """
    _log_workspace_error(exc, request)

    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={
            "error": "Authentication failed",
            "detail": "Invalid or missing authentication token",
            "error_code": "AUTHENTICATION_FAILED",
        },
        headers={"WWW-Authenticate": "Bearer", **_get_workspace_headers()},
    )


async def workspace_error_handler(request: Request, exc: WorkspaceError) -> JSONResponse:
    """Handle generic workspace errors.

    This is a catch-all handler for WorkspaceError instances that
    don't have more specific handlers.

    Args:
        request: FastAPI request object
        exc: WorkspaceError exception

    Returns:
        JSONResponse with 500 status
    """
    _log_workspace_error(exc, request)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "An unexpected workspace-related error occurred",
            "error_code": "WORKSPACE_ERROR",
        },
        headers=_get_workspace_headers(),
    )


def _get_workspace_headers() -> dict[str, str]:
    """Get workspace context headers for API responses.

    Returns:
        Dict containing workspace context headers
    """
    headers = {}

    try:
        context = ContextManager.get_context()
        if context and context.workspace_id:
            headers["X-Workspace-ID"] = context.workspace_id
    except Exception:  # noqa: S110
        # If context is not available, don't add headers
        pass

    return headers


# Registry of error handlers for easy registration
WORKSPACE_ERROR_HANDLERS = {
    WorkspaceAccessDenied: workspace_access_denied_handler,
    WorkspaceResourceNotFound: workspace_resource_not_found_handler,
    MissingWorkspaceContext: missing_workspace_context_handler,
    InvalidJWTToken: invalid_jwt_token_handler,
    WorkspaceError: workspace_error_handler,  # Catch-all handler
}
