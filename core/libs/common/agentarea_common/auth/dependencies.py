"""FastAPI dependencies for user and workspace context."""

from typing import Annotated

from fastapi import Depends, Request

from .context import UserContext
from .context_manager import ContextManager
from .jwt_handler import get_jwt_handler


async def get_user_context(request: Request) -> UserContext:
    """FastAPI dependency to extract user context from JWT token.
    
    This dependency extracts user_id and workspace_id from JWT token claims
    and returns a UserContext object. It also sets the context in the
    ContextManager for use throughout the request lifecycle.
    
    Args:
        request: FastAPI request object
        
    Returns:
        UserContext: User and workspace context from JWT token
        
    Raises:
        HTTPException: If token is missing, invalid, or lacks required claims
    """
    jwt_handler = get_jwt_handler()
    user_context = await jwt_handler.extract_user_context(request)

    # Set context in ContextManager for use throughout request
    ContextManager.set_context(user_context)

    return user_context


# Type alias for easier use in endpoint dependencies
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
