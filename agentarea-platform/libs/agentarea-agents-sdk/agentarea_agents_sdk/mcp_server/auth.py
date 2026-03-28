"""MCP auth middleware — extracts UserContext from request headers via ContextVar.

The middleware is **permissive**: it validates auth when present but lets
unauthenticated requests through so the MCP protocol handshake (Initialize,
Ping, etc.) can proceed.  Auth is enforced at tool execution time — if a
tool calls ``get_mcp_user_context()`` and no valid token was provided, a
``RuntimeError`` is raised and the tool returns an error to the client.
"""

import logging
from contextvars import ContextVar

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ContextVar holding the authenticated UserContext for the current request.
_mcp_user_context_var: ContextVar = ContextVar("mcp_user_context")


def get_mcp_user_context():
    """Read the current request's UserContext from the ContextVar.

    Raises ``RuntimeError`` if called outside an authenticated MCP request.
    """
    ctx = _mcp_user_context_var.get(None)
    if ctx is None:
        raise RuntimeError(
            "Authentication required. Provide a valid Bearer token "
            "in the Authorization header."
        )
    return ctx


class MCPAuthMiddleware:
    """Pure-ASGI middleware that extracts auth from MCP requests.

    Pure ASGI (not BaseHTTPMiddleware) so it correctly forwards lifespan events
    and does not buffer SSE streams.

    Permissive: validates token when ``Authorization: Bearer ...`` is present,
    stores the resulting ``UserContext`` in a ``ContextVar``, and lets the
    request proceed regardless.  Unauthenticated protocol messages (Initialize,
    Ping) pass through; tool handlers that need auth call
    ``get_mcp_user_context()`` which raises if no context was set.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Forward lifespan, websocket, etc. unchanged.
            await self.app(scope, receive, send)
            return

        token = _mcp_user_context_var.set(None)
        try:
            request = Request(scope, receive)
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                bearer_token = auth_header[len("bearer "):]
                await self._try_authenticate(bearer_token, request)
            await self.app(scope, receive, send)
        finally:
            _mcp_user_context_var.reset(token)

    async def _try_authenticate(self, bearer_token: str, request: Request) -> None:
        """Attempt to validate the token and set UserContext. Never raises."""
        try:
            from agentarea_common.auth.context import UserContext
            from agentarea_common.auth.dependencies import (
                _resolve_accessible_workspaces,
                _try_hydra_token,
                _validate_api_key,
                get_auth_provider,
            )

            _API_KEY_PREFIX = "aa_"

            # --- API key path ---
            if bearer_token.startswith(_API_KEY_PREFIX):
                user_context = await _validate_api_key(bearer_token, request)
                if user_context:
                    await _resolve_accessible_workspaces(user_context)
                    _mcp_user_context_var.set(user_context)
                    return

            # --- JWT path (Kratos then Hydra) ---
            auth_provider = get_auth_provider()
            auth_result = await auth_provider.verify_token(bearer_token)

            if auth_result.is_authenticated and auth_result.token:
                workspace_id = (
                    request.headers.get("X-Workspace-ID")
                    or auth_result.token.user_id
                )
                user_context = UserContext(
                    user_id=auth_result.token.user_id,
                    workspace_id=workspace_id,
                    roles=[],
                )
                await _resolve_accessible_workspaces(user_context)
                _mcp_user_context_var.set(user_context)
                return

            # Kratos failed — try Hydra OAuth
            hydra_context = await _try_hydra_token(bearer_token, request)
            if hydra_context is not None:
                await _resolve_accessible_workspaces(hydra_context)
                _mcp_user_context_var.set(hydra_context)
                return

            logger.debug("MCP auth: token validation failed (no provider accepted)")

        except Exception:
            logger.debug("MCP auth: token validation error", exc_info=True)
