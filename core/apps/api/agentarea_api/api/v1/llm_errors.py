"""API endpoints for LLM error monitoring."""

from typing import Any

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import APIRouter, Depends

# Import the global error handler
try:
    from agentarea_execution.handlers import llm_error_handler
except ImportError:
    # Fallback if execution module is not available
    llm_error_handler = None

router = APIRouter(prefix="/llm-errors", tags=["LLM Errors"])


@router.get("/summary")
async def get_llm_error_summary(
    user_context: UserContext = Depends(get_user_context)
) -> dict[str, Any]:
    """Get summary of LLM errors for monitoring."""
    if llm_error_handler is None:
        return {
            "error": "LLM error handler not available",
            "auth_failures": {},
            "total_auth_failures": 0
        }

    try:
        summary = llm_error_handler.get_error_summary()
        return {
            "status": "success",
            **summary
        }
    except Exception as e:
        return {
            "error": f"Failed to get error summary: {e!s}",
            "auth_failures": {},
            "total_auth_failures": 0
        }


@router.get("/auth-failures")
async def get_auth_failures(
    user_context: UserContext = Depends(get_user_context)
) -> dict[str, Any]:
    """Get detailed authentication failure information."""
    if llm_error_handler is None:
        return {
            "error": "LLM error handler not available",
            "failures": {}
        }

    try:
        return {
            "status": "success",
            "failures": llm_error_handler.auth_failures
        }
    except Exception as e:
        return {
            "error": f"Failed to get auth failures: {e!s}",
            "failures": {}
        }
