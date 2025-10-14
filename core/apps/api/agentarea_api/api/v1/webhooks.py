"""Webhook endpoints for trigger system."""

import logging
from typing import Any

from agentarea_api.api.deps.services import get_webhook_manager
from agentarea_common.auth.dependencies import UserContextDep
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.api_route(
    "/{webhook_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    summary="Handle webhook requests",
    description="Process incoming webhook requests for registered triggers",
)
async def handle_webhook(
    webhook_id: str, request: Request, webhook_manager=Depends(get_webhook_manager)
) -> Response:
    """Handle incoming webhook requests.

    This endpoint accepts all HTTP methods and routes them to the appropriate
    webhook trigger based on the webhook_id.

    Args:
        webhook_id: Unique identifier for the webhook
        request: FastAPI request object containing headers, body, etc.
        webhook_manager: Injected webhook manager service

    Returns:
        JSON response with success/error status
    """
    try:
        # Extract request data
        method = request.method
        headers = dict(request.headers)
        query_params = dict(request.query_params)

        # Get request body
        body = None
        content_type = headers.get("content-type", "").lower()

        if method in ["POST", "PUT", "PATCH"]:
            try:
                if "application/json" in content_type:
                    body = await request.json()
                elif "application/x-www-form-urlencoded" in content_type:
                    body = dict(await request.form())
                elif "multipart/form-data" in content_type:
                    body = dict(await request.form())
                else:
                    # Raw body as text
                    body_bytes = await request.body()
                    body = body_bytes.decode("utf-8") if body_bytes else None
            except Exception as e:
                logger.warning(f"Failed to parse request body for webhook {webhook_id}: {e}")
                body = None

        # Process webhook request
        result = await webhook_manager.handle_webhook_request(
            webhook_id=webhook_id,
            method=method,
            headers=headers,
            body=body,
            query_params=query_params,
        )

        # Return response
        status_code = result.get("status_code", 200)
        response_body = result.get("body", {"status": "success"})

        return JSONResponse(status_code=status_code, content=response_body)

    except Exception as e:
        logger.error(f"Unexpected error handling webhook {webhook_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error processing webhook"},
        )


@router.get(
    "/health",
    summary="Webhook system health check",
    description="Check if the webhook system is healthy and operational",
)
async def webhook_health_check(
    user_context: UserContextDep,
    webhook_manager=Depends(get_webhook_manager),
) -> dict[str, Any]:
    """Health check endpoint for webhook system.

    Returns:
        Dictionary with health status information
    """
    try:
        is_healthy = await webhook_manager.is_healthy()

        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "service": "webhook-manager",
            "timestamp": "2025-01-21T00:00:00Z",  # Would use actual timestamp
        }

    except Exception as e:
        logger.error(f"Webhook health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "webhook-manager",
            "error": str(e),
            "timestamp": "2025-01-21T00:00:00Z",  # Would use actual timestamp
        }


# Optional: Webhook management endpoints for debugging/admin
@router.get(
    "/debug/{webhook_id}",
    summary="Debug webhook configuration",
    description="Get debug information about a webhook (admin only)",
)
async def debug_webhook(
    webhook_id: str,
    user_context: UserContextDep,
    webhook_manager=Depends(get_webhook_manager),
) -> dict[str, Any]:
    """Debug endpoint to get information about a webhook.

    Note: This would typically require admin authentication in production.

    Args:
        webhook_id: Unique identifier for the webhook
        webhook_manager: Injected webhook manager service

    Returns:
        Dictionary with webhook debug information
    """
    try:
        # This is a simplified debug endpoint
        # In production, you'd want proper authentication and authorization

        return {
            "webhook_id": webhook_id,
            "status": "registered",  # Would check actual registration status
            "debug_info": {
                "message": "Debug endpoint - would show webhook configuration in production"
            },
        }

    except Exception as e:
        logger.error(f"Error debugging webhook {webhook_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error debugging webhook: {e!s}")
