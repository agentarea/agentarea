"""Workspace-related exception classes."""


class WorkspaceError(Exception):
    """Base exception for workspace-related errors.

    This is the base class for all workspace-related exceptions.
    It includes workspace context information for better error tracking.
    """

    def __init__(
        self,
        message: str,
        workspace_id: str | None = None,
        user_id: str | None = None,
        resource_id: str | None = None,
    ):
        """Initialize workspace error.

        Args:
            message: Error message
            workspace_id: ID of the workspace where error occurred
            user_id: ID of the user who triggered the error
            resource_id: ID of the resource that caused the error
        """
        super().__init__(message)
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.resource_id = resource_id
        self.message = message

    def __str__(self) -> str:
        """Return string representation with context."""
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

    This exception is raised when a user attempts to access a resource
    that belongs to a different workspace than their current context.
    """

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
    """Raised when workspace context is missing from request.

    This exception is raised when a request lacks the required
    user and workspace context information.
    """

    def __init__(self, missing_field: str, user_id: str | None = None):
        """Initialize missing workspace context error.

        Args:
            missing_field: Name of the missing context field
            user_id: ID of the user if available
        """
        message = f"Missing required context field: {missing_field}"
        super().__init__(message=message, user_id=user_id)
        self.missing_field = missing_field


class InvalidJWTToken(WorkspaceError):  # noqa: N818
    """Raised when JWT token is invalid or missing required claims.

    This exception is raised when JWT token validation fails or
    when the token lacks required claims for workspace context.
    """

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

    This exception is used instead of generic NotFound errors to provide
    workspace context and ensure proper 404 responses for cross-workspace
    access attempts.
    """

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
        super().__init__(
            message=message, workspace_id=workspace_id, user_id=user_id, resource_id=resource_id
        )
        self.resource_type = resource_type
