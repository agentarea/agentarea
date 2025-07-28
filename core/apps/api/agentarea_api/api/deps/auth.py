"""Authentication dependencies for FastAPI endpoints.

This module provides dependency injection functions for authentication
and authorization used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from agentarea_common.auth import UserContext, UserContextDep, get_user_context

logger = logging.getLogger(__name__)

# Placeholder for a default test user ID (for backward compatibility)
DEFAULT_USER_ID = "test-user-123"


async def get_current_user_id(
    request: Request,
    x_user_id: str | None = Header(None, description="User ID header (for testing)"),
) -> str:
    """Get the current user ID from the request.

    This is a backward compatibility function. New code should use get_user_context
    and UserContextDep instead.

    Args:
        request: The FastAPI request object
        x_user_id: Optional user ID provided in headers (for testing)

    Returns:
        str: The user ID

    Raises:
        HTTPException: If authentication fails
    """
    # First try to get from JWT context
    try:
        user_context = await get_user_context(request)
        return user_context.user_id
    except HTTPException:
        # Fall back to legacy header/query parameter method for testing
        pass

    # First check if user ID is provided in header (for testing)
    if x_user_id:
        logger.debug(f"Using user ID from header: {x_user_id}")
        return x_user_id

    # Check if user ID is in query parameters (for testing)
    user_id = request.query_params.get("user_id")
    if user_id:
        logger.debug(f"Using user ID from query parameter: {user_id}")
        return user_id

    # For now, return a default test user ID
    logger.debug(f"Using default user ID: {DEFAULT_USER_ID}")
    return DEFAULT_USER_ID


async def get_admin_user_id(
    user_id: str = Depends(get_current_user_id),
) -> str:
    """Get the current user ID and verify admin privileges.

    This is a simplified placeholder implementation. In a production environment,
    this would check user roles and permissions.

    Args:
        user_id: The user ID from get_current_user_id

    Returns:
        str: The user ID if admin

    Raises:
        HTTPException: If user is not an admin
    """
    # In a real implementation, check if user has admin role
    # For now, only allow the default test user as admin
    if user_id != DEFAULT_USER_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to perform this action"
        )

    return user_id


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
    if "admin" not in user_context.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Not authorized to perform this action"
        )

    return user_context


# Type alias for admin context dependency
AdminUserContextDep = Annotated[UserContext, Depends(get_admin_user_context)]
