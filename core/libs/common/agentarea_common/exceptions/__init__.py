"""Exception classes for AgentArea.

This module provides custom exception classes for workspace-related errors
and other common error scenarios.
"""

from .handlers import (
    WORKSPACE_ERROR_HANDLERS,
    invalid_jwt_token_handler,
    missing_workspace_context_handler,
    workspace_access_denied_handler,
    workspace_error_handler,
    workspace_resource_not_found_handler,
)
from .registration import (
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
    # Exception classes
    "WorkspaceError",
    "WorkspaceAccessDenied",
    "MissingWorkspaceContext",
    "InvalidJWTToken",
    "WorkspaceResourceNotFound",
    # Error handlers
    "workspace_access_denied_handler",
    "workspace_resource_not_found_handler",
    "missing_workspace_context_handler",
    "invalid_jwt_token_handler",
    "workspace_error_handler",
    "WORKSPACE_ERROR_HANDLERS",
    # Registration utilities
    "register_workspace_error_handlers",
    "register_single_workspace_error_handler",
    # Utility functions
    "raise_workspace_access_denied",
    "raise_workspace_resource_not_found",
    "check_workspace_access",
    "ensure_workspace_resource_exists",
    "format_resource_id",
]
