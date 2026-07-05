"""MCP auth middleware — extracts UserContext from request headers via ContextVar.

The middleware allows the MCP protocol handshake (initialize, notifications/*,
ping) without authentication.  All other methods — including ``tools/list``,
``tools/call``, ``resources/*``, ``prompts/*`` — require a valid Bearer token
or an established (previously authenticated) session.

Unauthenticated requests to protected methods receive HTTP 401 with an
``WWW-Authenticate: Bearer resource_metadata="…"`` header (RFC 9728) so that
MCP clients (Cursor, Claude Desktop) can discover the OAuth flow automatically.

Session-aware: when a Bearer token is validated on the first request (Initialize),
the resulting UserContext is cached by ``mcp-session-id``.  Subsequent requests
in the same session (which carry only the session ID, no Bearer) restore the
cached context automatically.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ContextVar holding the authenticated UserContext for the current request.
_mcp_user_context_var: ContextVar[Any] = ContextVar("mcp_user_context")

# MCP JSON-RPC methods that are allowed without authentication.
_UNAUTHENTICATED_METHODS = frozenset({"initialize", "ping"})


def get_mcp_user_context():
    """Read the current request's UserContext from the ContextVar.

    Raises ``RuntimeError`` if called outside an authenticated MCP request.
    """
    ctx = _mcp_user_context_var.get(None)
    if ctx is None:
        raise RuntimeError(
            "Authentication required. Provide a valid Bearer token in the Authorization header."
        )
    return ctx


@contextmanager
def use_mcp_user_context(user_context: Any) -> Iterator[None]:
    """Temporarily bind a UserContext for non-HTTP internal tool execution.

    Platform toolsets use the same ContextVar whether they are called through
    the MCP HTTP server or from the Temporal worker's code-tool activity. The
    worker path already has an authenticated task context, so it should bind
    that context directly instead of asking the LLM to provide a Bearer token.
    """
    token = _mcp_user_context_var.set(user_context)
    try:
        yield
    finally:
        _mcp_user_context_var.reset(token)


def _is_handshake_method(method: str) -> bool:
    """Return True for MCP methods that must work without authentication."""
    return method in _UNAUTHENTICATED_METHODS or method.startswith("notifications/")


def _www_authenticate_header() -> str:
    """RFC 9728 WWW-Authenticate header for OAuth protected-resource discovery."""
    try:
        from agentarea_common.config import get_settings

        api_base = get_settings().app.API_BASE_URL.rstrip("/")
        return f'Bearer resource_metadata="{api_base}/.well-known/oauth-protected-resource"'
    except Exception:
        return "Bearer"


async def _read_body(receive: Receive) -> bytes:
    """Read the complete request body from the ASGI receive channel."""
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    return body


class MCPAuthMiddleware:
    """Pure-ASGI middleware that authenticates MCP requests.

    Allows handshake methods (initialize, notifications/*, ping) without auth.
    All other methods require a valid Bearer token or an established session.
    Unauthenticated requests to protected methods receive HTTP 401 with
    RFC 9728 WWW-Authenticate header for OAuth discovery.

    Session-aware: on the first authenticated request (Initialize with Bearer
    token), the middleware validates the token, caches the resulting
    UserContext keyed by ``mcp-session-id``, and restores it on subsequent
    requests that carry only the session ID.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        # session_id → UserContext cache (lives for the process lifetime)
        self._session_contexts: dict[str, Any] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Read full request body up-front so we can inspect the JSON-RPC method
        # before deciding whether to forward or reject.
        body = await _read_body(receive)
        method, request_id = _parse_jsonrpc(body)

        # Build a Request for header access (body will be replayed separately
        # for the downstream handler — Request itself is only used for headers).
        request = Request(scope, _make_replay_receive(body))
        session_id = request.headers.get("mcp-session-id")
        auth_header = request.headers.get("authorization", "")

        token = _mcp_user_context_var.set(None)
        captured_session_id: str | None = None

        try:
            # ---------- attempt authentication ----------
            if auth_header.lower().startswith("bearer "):
                bearer_token = auth_header[len("bearer ") :]
                await self._try_authenticate(bearer_token, request)
            elif session_id and session_id in self._session_contexts:
                _mcp_user_context_var.set(self._session_contexts[session_id])

            # ---------- gate: reject protected methods without auth ----------
            ctx = _mcp_user_context_var.get(None)
            if ctx is None and not _is_handshake_method(method):
                logger.info(
                    "MCP auth: rejecting unauthenticated request method=%s session=%s",
                    method,
                    session_id,
                )
                await _send_401(send, request_id)
                return

            # ---------- forward to downstream handler ----------
            replay = _make_replay_receive(body)

            async def send_wrapper(message):
                nonlocal captured_session_id
                if message["type"] == "http.response.start":
                    for key, value in message.get("headers", []):
                        if key == b"mcp-session-id":
                            captured_session_id = value.decode()
                            break
                await send(message)

            await self.app(scope, replay, send_wrapper)
        finally:
            ctx = _mcp_user_context_var.get(None)
            if ctx is not None and captured_session_id:
                self._session_contexts[captured_session_id] = ctx
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

            api_key_prefix = "aat_"

            # --- API key path ---
            if bearer_token.startswith(api_key_prefix):
                user_context = await _validate_api_key(bearer_token, request)
                if user_context:
                    await _resolve_accessible_workspaces(user_context)
                    _mcp_user_context_var.set(user_context)
                    return

            # --- JWT path (Kratos then Hydra) ---
            auth_provider = get_auth_provider()
            auth_result = await auth_provider.verify_token(bearer_token)

            if auth_result.is_authenticated and auth_result.token:
                workspace_id = request.headers.get("X-Workspace-ID") or auth_result.token.user_id
                user_context = UserContext(
                    user_id=auth_result.token.user_id,
                    workspace_id=workspace_id,
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


# ---------------------------------------------------------------------------
# Helpers (module-level for testability)
# ---------------------------------------------------------------------------


def _parse_jsonrpc(body: bytes) -> tuple[str, Any]:
    """Extract (method, id) from a JSON-RPC request body."""
    try:
        data = json.loads(body)
        return data.get("method", ""), data.get("id")
    except (json.JSONDecodeError, AttributeError):
        return "", None


def _make_replay_receive(body: bytes) -> Receive:
    """Return an ASGI ``receive`` callable that replays *body* exactly once."""
    _sent = False

    async def replay() -> Message:
        nonlocal _sent
        if not _sent:
            _sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # After the body has been delivered the downstream handler should not
        # call receive again — block forever to avoid returning garbage.
        import asyncio

        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    return replay


async def _send_401(send: Send, request_id: Any) -> None:
    """Send an HTTP 401 response with RFC 9728 WWW-Authenticate header."""
    www_auth = _www_authenticate_header()
    error_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32600,
                "message": "Authentication required. Provide a valid Bearer token.",
            },
        }
    ).encode()

    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                [b"content-type", b"application/json"],
                [b"www-authenticate", www_auth.encode()],
            ],
        }
    )
    await send({"type": "http.response.body", "body": error_body})
