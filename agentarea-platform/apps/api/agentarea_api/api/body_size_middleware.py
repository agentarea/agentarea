"""Request body size limit middleware.

Rejects oversized requests with 413. A cheap DoS guard for an API that has no
gateway in front (API4 — unrestricted resource consumption).

Two checks, because a body need not declare its size:

* A ``Content-Length`` above the limit is refused before anything is read.
* Every body is also counted as it streams in, so a ``Transfer-Encoding:
  chunked`` request (no ``Content-Length`` at all) or one that sends more than
  it declared is cut off once it crosses the limit, instead of being buffered
  in full by whatever handler reads it.

Pure ASGI rather than ``BaseHTTPMiddleware``: the limit has to sit on the
``receive`` channel the application reads the body from.
"""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_DETAIL = "Request body too large"


class RequestBodyTooLarge(HTTPException):
    """Raised from ``receive`` once the streamed body crosses the limit.

    An ``HTTPException`` so that FastAPI's body parsing re-raises it instead of
    turning it into a 400, and the exception middleware answers 413.
    """

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=_DETAIL)


def _too_large() -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": _DETAIL})


class BodySizeLimitMiddleware:
    """Reject requests whose body, declared or streamed, exceeds ``max_bytes``."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _declared_length(Headers(scope=scope))
        if declared is not None and declared > self.max_bytes:
            await _too_large()(scope, receive, send)
            return

        received = 0
        exceeded = False
        response_started = False
        answered = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                raise RequestBodyTooLarge()
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise RequestBodyTooLarge()
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started, answered
            if answered:
                return
            if message["type"] == "http.response.start":
                if exceeded:
                    # Whatever the application made of the cut-off body (a 413
                    # from the exception handler, or a 400/500 from a handler
                    # that caught the error), the answer is 413.
                    answered = True
                    response_started = True
                    await _too_large()(scope, receive, send)
                    return
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            # Any failure once the body crossed the limit is that limit: the
            # application may have wrapped or replaced the error on its way out.
            if not exceeded:
                raise
            if answered:
                return
            if response_started:
                raise
            await _too_large()(scope, receive, send)


def _declared_length(headers: Headers) -> int | None:
    content_length = headers.get("content-length")
    if content_length is None:
        return None
    try:
        return int(content_length)
    except ValueError:
        return None
