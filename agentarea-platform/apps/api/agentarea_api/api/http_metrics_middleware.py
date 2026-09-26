"""Request latency and concurrency, labelled by route template.

A plain ASGI middleware rather than ``BaseHTTPMiddleware`` so streamed
responses (SSE) pass through untouched. The route label is the matched
template, never the raw path: a path carries workspace slugs and object ids,
and each would mint its own time series.
"""

from time import perf_counter

from agentarea_common.observability.metrics import (
    HTTP_REQUEST_DURATION,
    HTTP_REQUESTS_IN_PROGRESS,
)
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNMATCHED_ROUTE = "<unmatched>"


def route_template(scope: Scope) -> str:
    """The template of the route ``scope`` resolves to, as the router would pick it."""
    partial: str | None = None
    for route in scope["app"].router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route.path
        if match == Match.PARTIAL and partial is None:
            partial = route.path
    return partial or UNMATCHED_ROUTE


class HTTPMetricsMiddleware:
    """Record ``agentarea_http_*`` metrics for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        route = route_template(scope)
        # A request that dies before sending a response is answered 500 by the
        # server, so that is what it counts as.
        status = "5xx"

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = f"{message['status'] // 100}xx"
            await send(message)

        in_progress = HTTP_REQUESTS_IN_PROGRESS.labels(method=method, route=route)
        in_progress.inc()
        started = perf_counter()
        try:
            await self.app(scope, receive, send_with_status)
        finally:
            HTTP_REQUEST_DURATION.labels(method=method, route=route, status=status).observe(
                perf_counter() - started
            )
            in_progress.dec()
