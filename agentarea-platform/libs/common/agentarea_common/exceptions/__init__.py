"""Exception classes and unified error handling for AgentArea.

Provides the :class:`AppError` base (rendered as RFC 9457 problem+json), semantic
HTTP subclasses, workspace exceptions, and the handler/registration utilities.
"""

from .errors import (
    PROBLEM_JSON_MEDIA_TYPE,
    AppError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    problem_dict,
    problem_response,
)
from .handlers import (
    ERROR_HANDLERS,
    WORKSPACE_ERROR_HANDLERS,
    app_error_handler,
    http_exception_handler,
    integrity_error_handler,
    permission_error_handler,
    unhandled_exception_handler,
    validation_exception_handler,
    workspace_error_handler,
)
from .registration import (
    register_error_handlers,
    register_single_error_handler,
    register_single_workspace_error_handler,
    register_workspace_error_handlers,
)
from .utils import (
    check_workspace_access,
    ensure_workspace_resource_exists,
    format_resource_id,
    raise_workspace_access_denied,
    raise_workspace_resource_not_found,
)
from .workspace import (
    InvalidJWTToken,
    MissingWorkspaceContext,
    WorkspaceAccessDenied,
    WorkspaceError,
    WorkspaceResourceNotFound,
)

__all__ = [
    "ERROR_HANDLERS",
    "PROBLEM_JSON_MEDIA_TYPE",
    "WORKSPACE_ERROR_HANDLERS",
    # Base error model + semantic subclasses
    "AppError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "InvalidJWTToken",
    "MissingWorkspaceContext",
    "NotFoundError",
    "PermissionDeniedError",
    # Workspace exception classes
    "WorkspaceAccessDenied",
    "WorkspaceError",
    "WorkspaceResourceNotFound",
    "app_error_handler",
    "check_workspace_access",
    "ensure_workspace_resource_exists",
    "format_resource_id",
    "http_exception_handler",
    "integrity_error_handler",
    "permission_error_handler",
    # problem+json helpers
    "problem_dict",
    "problem_response",
    # Utility functions
    "raise_workspace_access_denied",
    "raise_workspace_resource_not_found",
    # Registration utilities
    "register_error_handlers",
    "register_single_error_handler",
    "register_single_workspace_error_handler",
    "register_workspace_error_handlers",
    "unhandled_exception_handler",
    "validation_exception_handler",
    "workspace_error_handler",
]
