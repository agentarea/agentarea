"""Utility functions for raising workspace-related exceptions."""

from uuid import UUID

from ..auth.context_manager import ContextManager
from .workspace import WorkspaceAccessDenied, WorkspaceResourceNotFound


def raise_workspace_access_denied(
    resource_type: str, resource_id: str, resource_workspace_id: str | None = None
) -> None:
    """Raise WorkspaceAccessDenied exception with current context.

    Args:
        resource_type: Type of resource being accessed
        resource_id: ID of the resource being accessed
        resource_workspace_id: Workspace ID that owns the resource (optional)

    Raises:
        WorkspaceAccessDenied: Always raised with current context
    """
    context = ContextManager.get_context()
    current_workspace_id = context.workspace_id if context else "unknown"
    user_id = context.user_id if context else None

    raise WorkspaceAccessDenied(
        resource_type=resource_type,
        resource_id=resource_id,
        current_workspace_id=current_workspace_id,
        resource_workspace_id=resource_workspace_id,
        user_id=user_id,
    )


def raise_workspace_resource_not_found(resource_type: str, resource_id: str) -> None:
    """Raise WorkspaceResourceNotFound exception with current context.

    Args:
        resource_type: Type of resource
        resource_id: ID of the resource

    Raises:
        WorkspaceResourceNotFound: Always raised with current context
    """
    context = ContextManager.get_context()
    workspace_id = context.workspace_id if context else "unknown"
    user_id = context.user_id if context else None

    raise WorkspaceResourceNotFound(
        resource_type=resource_type,
        resource_id=resource_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )


def check_workspace_access(
    resource_workspace_id: str, resource_type: str, resource_id: str
) -> None:
    """Check if current user has access to resource in their workspace.

    Args:
        resource_workspace_id: Workspace ID that owns the resource
        resource_type: Type of resource being accessed
        resource_id: ID of the resource being accessed

    Raises:
        WorkspaceAccessDenied: If resource belongs to different workspace
    """
    context = ContextManager.get_context()
    if not context:
        raise_workspace_access_denied(resource_type, resource_id)

    if resource_workspace_id != context.workspace_id:
        raise_workspace_access_denied(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_workspace_id=resource_workspace_id,
        )


def ensure_workspace_resource_exists(
    resource: object | None, resource_type: str, resource_id: str
) -> object:
    """Ensure resource exists and raise workspace-specific error if not.

    Args:
        resource: The resource object or None
        resource_type: Type of resource
        resource_id: ID of the resource

    Returns:
        The resource object if it exists

    Raises:
        WorkspaceResourceNotFound: If resource is None
    """
    if resource is None:
        raise_workspace_resource_not_found(resource_type, resource_id)

    return resource


def format_resource_id(resource_id: UUID | str) -> str:
    """Format resource ID for error messages.

    Args:
        resource_id: UUID or string resource ID

    Returns:
        String representation of the resource ID
    """
    if isinstance(resource_id, UUID):
        return str(resource_id)
    return resource_id
