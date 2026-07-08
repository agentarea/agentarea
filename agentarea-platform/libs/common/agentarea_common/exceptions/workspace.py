"""Workspace-related exception classes.

These are :class:`AppError` subclasses, so they render as RFC 9457 problem+json
through the unified handler. The ``detail`` surfaced to the client is a *safe*,
generic message (e.g. cross-workspace access returns a 404 "does not exist" to
avoid leaking resource existence); the verbose context (workspace_id, user_id,
resource_id) lives on the instance and in ``__str__`` for server-side logging
only.
"""

from __future__ import annotations

from fastapi import status

from .errors import AppError


class WorkspaceError(AppError):
    """Base exception for workspace-related errors.

    Carries workspace context for logging while exposing only a generic,
    client-safe ``detail`` in the response body.
    """

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "workspace_error"
    # Client-safe detail; subclasses override (or set per-instance).
    safe_detail = "An unexpected workspace-related error occurred"

    def __init__(
        self,
        message: str,
        workspace_id: str | None = None,
        user_id: str | None = None,
        resource_id: str | None = None,
    ):
        """Initialize workspace error.

        Args:
            message: Verbose internal message (logged, never sent to the client).
            workspace_id: ID of the workspace where error occurred
            user_id: ID of the user who triggered the error
            resource_id: ID of the resource that caused the error
        """
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.resource_id = resource_id
        self.message = message
        super().__init__(detail=self.safe_detail)

    def __str__(self) -> str:
        """Return verbose representation with context (for logging)."""
        context_parts = []
        if self.workspace_id:
            context_parts.append(f"workspace_id={self.workspace_id}")
        if self.user_id:
            context_parts.append(f"user_id={self.user_id}")
        if self.resource_id:
            context_parts.append(f"resource_id={self.resource_id}")

        if context_parts:
            context = " (" + ", ".join(context_parts) + ")"
            return f"{self.message}{context}"
        return self.message


class WorkspaceAccessDenied(WorkspaceError):  # noqa: N818
    """Raised when user tries to access resource from different workspace.

    Rendered as 404 (not 403) with a generic message so existence of resources
    in other workspaces is not leaked.
    """

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    safe_detail = "The requested resource does not exist or you don't have access to it"

    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        current_workspace_id: str,
        resource_workspace_id: str | None = None,
        user_id: str | None = None,
    ):
        """Initialize workspace access denied error.

        Args:
            resource_type: Type of resource being accessed (e.g., 'agent', 'task')
            resource_id: ID of the resource being accessed
            current_workspace_id: User's current workspace ID
            resource_workspace_id: Workspace ID that owns the resource
            user_id: ID of the user attempting access
        """
        if resource_workspace_id:
            message = (
                f"Access denied to {resource_type} '{resource_id}'. "
                f"Resource belongs to workspace '{resource_workspace_id}' "
                f"but user is in workspace '{current_workspace_id}'"
            )
        else:
            message = (
                f"Access denied to {resource_type} '{resource_id}'. "
                f"Resource not found in workspace '{current_workspace_id}'"
            )

        super().__init__(
            message=message,
            workspace_id=current_workspace_id,
            user_id=user_id,
            resource_id=resource_id,
        )
        self.resource_type = resource_type
        self.current_workspace_id = current_workspace_id
        self.resource_workspace_id = resource_workspace_id


class MissingWorkspaceContext(WorkspaceError):  # noqa: N818
    """Raised when workspace context is missing from request."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "missing_context"

    def __init__(self, missing_field: str, user_id: str | None = None):
        """Initialize missing workspace context error.

        Args:
            missing_field: Name of the missing context field
            user_id: ID of the user if available
        """
        message = f"Missing required context field: {missing_field}"
        self.safe_detail = f"Request must include valid {missing_field} information"
        super().__init__(message=message, user_id=user_id)
        self.missing_field = missing_field


class InvalidJWTToken(WorkspaceError):  # noqa: N818
    """Raised when JWT token is invalid or missing required claims."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "authentication_failed"
    safe_detail = "Invalid or missing authentication token"

    def __init__(self, reason: str, token_present: bool = False):
        """Initialize invalid JWT token error.

        Args:
            reason: Reason why the token is invalid
            token_present: Whether a token was present in the request
        """
        if token_present:
            message = f"Invalid JWT token: {reason}"
        else:
            message = f"Missing or invalid JWT token: {reason}"

        super().__init__(message=message)
        self.reason = reason
        self.token_present = token_present


class WorkspaceResourceNotFound(WorkspaceError):  # noqa: N818
    """Raised when a resource is not found in the current workspace.

    Used instead of generic NotFound errors so cross-workspace access attempts
    return a workspace-scoped 404.
    """

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"

    def __init__(
        self, resource_type: str, resource_id: str, workspace_id: str, user_id: str | None = None
    ):
        """Initialize workspace resource not found error.

        Args:
            resource_type: Type of resource (e.g., 'agent', 'task')
            resource_id: ID of the resource
            workspace_id: Current workspace ID
            user_id: ID of the user making the request
        """
        message = f"{resource_type.title()} '{resource_id}' not found in workspace '{workspace_id}'"
        self.safe_detail = f"The requested {resource_type} does not exist"
        super().__init__(
            message=message, workspace_id=workspace_id, user_id=user_id, resource_id=resource_id
        )
        self.resource_type = resource_type
