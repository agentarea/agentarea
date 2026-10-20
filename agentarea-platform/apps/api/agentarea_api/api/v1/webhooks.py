"""Public webhook sink: ``/webhooks/{webhook_id}`` records a source's event in its stream."""

import json
import logging
from typing import Any
from urllib.parse import parse_qsl

from agentarea_api.api.deps.services import get_public_webhook_manager
from agentarea_api.api.rate_limit import limit_webhook
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.utils.pg_text import pg_text_problem
from agentarea_streams.domain.keys import MAX_REQUEST_BYTES
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class RequestTooLargeError(Exception):
    pass


@router.get("/health", dependencies=[unrestricted("liveness probe, returns no workspace data")])
async def webhook_health_check(
    webhook_manager=Depends(get_public_webhook_manager),
) -> dict[str, Any]:
    """Health check endpoint for webhook system."""
    try:
        is_healthy = await webhook_manager.is_healthy()
        return {"status": "healthy" if is_healthy else "unhealthy", "service": "webhook-manager"}
    except Exception as e:
        logger.exception(f"Webhook health check failed: {e}")
        return {"status": "unhealthy", "service": "webhook-manager"}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "error", "message": message})


def _refuse_non_finite(constant: str) -> float:
    raise ValueError(f"{constant} is not a JSON number")


async def read_limited(request: Request, limit: int = MAX_REQUEST_BYTES) -> bytes:
    """The request body, refused past ``limit`` bytes before it is all read."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise RequestTooLargeError
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise RequestTooLargeError
        chunks.append(chunk)
    body = b"".join(chunks)
    # Starlette re-reads a consumed stream from here, so request.form() still works.
    request._body = body
    return body


async def parse_body(request: Request, raw: bytes, content_type: str) -> Any:
    """JSON strictly; form fields as text, form files as inline attachments; else text."""
    if "application/json" in content_type or content_type.endswith("+json"):
        return json.loads(raw, parse_constant=_refuse_non_finite) if raw else None
    if "application/x-www-form-urlencoded" in content_type:
        return dict(parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
    if "multipart/form-data" in content_type:
        import base64

        fields: dict[str, Any] = {}
        files: list[dict[str, Any]] = []
        async with request.form() as form:
            for name, value in form.multi_items():
                if isinstance(value, str):
                    fields[name] = value
                    continue
                data = await value.read()
                files.append(
                    {
                        "field": name,
                        "name": value.filename or name,
                        "mime": value.content_type,
                        "size": len(data),
                        "content_base64": base64.b64encode(data).decode("ascii"),
                    }
                )
        if files:
            fields["attachments"] = files
        return fields
    return raw.decode("utf-8") if raw else None


@router.post(
    "/{webhook_id}",
    operation_id="handle_webhook_webhooks__webhook_id__post",
    summary="Handle webhook requests",
    description="Record an incoming webhook in its stream",
    dependencies=[
        unrestricted("public webhook sink; authenticity is the signed payload, not a session")
    ],
)
async def handle_webhook(
    webhook_id: str,
    request: Request,
    _rate_limited: None = Depends(limit_webhook),
    webhook_manager=Depends(get_public_webhook_manager),
):
    """Verify the request by its source's catalog entry and record it as one event."""
    try:
        raw = await read_limited(request)
    except RequestTooLargeError:
        return _error(413, f"The request is larger than {MAX_REQUEST_BYTES} bytes")
    content_type = request.headers.get("content-type", "").lower()
    try:
        body = await parse_body(request, raw, content_type)
    except (ValueError, UnicodeDecodeError) as error:
        return _error(400, f"Body cannot be read: {error}")
    if problem := pg_text_problem(body):
        # Postgres cannot store it; accepting it would lose the event later.
        return _error(422, f"Body cannot be stored: {problem}")
    try:
        result = await webhook_manager.handle_webhook_request(
            webhook_id=webhook_id,
            method=request.method,
            headers=dict(request.headers),
            body=body,
            raw_body=raw,
        )
    except Exception:
        logger.exception("Unexpected error handling webhook %s", webhook_id)
        return _error(500, "Internal server error processing webhook")
    return JSONResponse(status_code=result["status_code"], content=result["body"])
