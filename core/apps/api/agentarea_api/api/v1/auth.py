"""Authentication endpoints for testing."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/users/me")
async def get_current_user(request: Request):
    """Get current user information.
    
    This endpoint returns the user information extracted from the JWT token.
    """
    # Access user information from request state (added by JWT middleware)
    user_id = getattr(request.state, "user_id", None)
    user_info = getattr(request.state, "user", {})
    
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"}
        )
    
    return {
        "user_id": user_id,
        "user_info": user_info
    }


@router.get("/token")
async def get_token_info(request: Request):
    """Get token information for debugging.
    
    This endpoint returns information about the current authentication state.
    """
    # Access user information from request state (added by JWT middleware)
    user_id = getattr(request.state, "user_id", None)
    user_info = getattr(request.state, "user", {})
    
    return {
        "authenticated": user_id is not None,
        "user_id": user_id,
        "user_info": user_info
    }
