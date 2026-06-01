"""Authentication dependencies for FastAPI endpoints.

This module provides dependency injection functions for authentication
and authorization used across the AgentArea API endpoints.
"""

import logging
from typing import Annotated

from agentarea_common.auth import UserContext, UserContextDep
from fastapi import Depends, HTTPException, status

logger = logging.getLogger(__name__)


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
