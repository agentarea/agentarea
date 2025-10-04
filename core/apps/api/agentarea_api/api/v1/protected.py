"""Protected endpoints for testing authentication."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/protected", tags=["protected"])


@router.get("/test")
async def test_protected_endpoint(request: Request):
    """Test endpoint to verify authentication is working.

    This endpoint requires a valid JWT token to access.
    """
    # Access user information from request state (added by JWT middleware)
    user_id = getattr(request.state, "user_id", None)
    user_info = getattr(request.state, "user", {})

    return {
        "message": "Authentication successful!",
        "user_id": user_id,
        "user_info": user_info,
        "authenticated": user_id is not None,
    }


@router.get("/user")
async def get_user_info(request: Request):
    """Get user information from the JWT token.

    This endpoint returns the user information extracted from the JWT token.
    """
    # Access user information from request state (added by JWT middleware)
    user_id = getattr(request.state, "user_id", None)
    user_info = getattr(request.state, "user", {})

    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

    return {"user_id": user_id, "user_info": user_info}
