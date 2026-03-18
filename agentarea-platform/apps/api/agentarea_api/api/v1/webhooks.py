"""Webhook endpoints for trigger system."""

import logging
from typing import Any

from agentarea_api.api.deps.services import get_public_webhook_manager
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/health")
async def webhook_health_check(
    webhook_manager=Depends(get_public_webhook_manager),
) -> dict[str, Any]:
    """Health check endpoint for webhook system."""
    try:
        is_healthy = await webhook_manager.is_healthy()
        return {"status": "healthy" if is_healthy else "unhealthy", "service": "webhook-manager"}
    except Exception as e:
        logger.error(f"Webhook health check failed: {e}")
        return {"status": "unhealthy", "service": "webhook-manager", "error": str(e)}


@router.api_route(
    "/{webhook_id}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    summary="Handle webhook requests",
    description="Process incoming webhook requests for registered triggers",
)
async def handle_webhook(
    webhook_id: str, request: Request, webhook_manager=Depends(get_public_webhook_manager)
):
    """Handle incoming webhook requests from external services (Telegram, Slack, GitHub, etc.)."""
    try:
        method = request.method
        headers = dict(request.headers)
        query_params = dict(request.query_params)

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
                    body_bytes = await request.body()
                    body = body_bytes.decode("utf-8") if body_bytes else None
            except Exception as e:
                logger.warning(f"Failed to parse request body for webhook {webhook_id}: {e}")
                body = None

        result = await webhook_manager.handle_webhook_request(
            webhook_id=webhook_id,
            method=method,
            headers=headers,
            body=body,
            query_params=query_params,
        )

        status_code = result.get("status_code", 200)
        response_body = result.get("body", {"status": "success"})
        return JSONResponse(status_code=status_code, content=response_body)

    except Exception as e:
        logger.error(f"Unexpected error handling webhook {webhook_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error processing webhook"},
        )
