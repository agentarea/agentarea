"""Authentication dependencies for FastAPI endpoints.

This module provides dependency injection functions for authentication
and authorization used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from agentarea_common.auth import UserContext, UserContextDep
from fastapi import Depends, Header, HTTPException, status

logger = logging.getLogger(__name__)


async def get_workspace_id(
    x_workspace_id: str | None = Header(
        None,
        description="Workspace ID for data isolation. Required for most endpoints.",
        alias="X-Workspace-ID",
    ),
    user_context: UserContextDep | None = None,
) -> str:
    """Get the workspace ID from the request header or user context.

    Args:
        x_workspace_id: Workspace ID provided in X-Workspace-ID header
        user_context: User context from authentication

    Returns:
        str: The workspace ID from header, or user's workspace_id from context

    Note: This function is deprecated. Use UserContextDep.workspace_id instead.
    """
    if x_workspace_id:
        return x_workspace_id
    if user_context:
        return user_context.workspace_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Workspace ID is required but not provided"
    )


# Type alias for workspace dependency
WorkspaceDep = Annotated[str, Depends(get_workspace_id)]


# New context-based dependencies
async def get_admin_user_context(
    user_context: UserContextDep,
) -> UserContext:
    """Get the current user context and verify admin privileges.

    Args:
        user_context: The user context from get_user_context

    Returns:
        UserContext: The user context if admin

    Raises:
        HTTPException: If user is not an admin
    """
    # In a real implementation, check if user has admin role
    # For now, check if user has admin role in their roles list
    if not user_context.roles or "admin" not in user_context.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to perform this action"
        )

    return user_context


# Type alias for admin context dependency
AdminUserContextDep = Annotated[UserContext, Depends(get_admin_user_context)]
