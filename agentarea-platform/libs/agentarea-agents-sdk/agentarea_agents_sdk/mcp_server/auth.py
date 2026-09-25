"""MCP auth middleware — authenticates every protected request independently.

The middleware allows the legacy MCP handshake (``initialize``, notifications/*
and ``ping``) without authentication.  All other methods — including
``server/discover`` on the 2026-07-28 wire, ``tools/list``, ``tools/call``,
``resources/*`` and ``prompts/*`` — require a valid Bearer token on that
request.

Unauthenticated requests to protected methods receive HTTP 401 with a
``WWW-Authenticate: Bearer resource_metadata="…"`` header (RFC 9728) so that
MCP clients can discover the OAuth flow automatically.  Modern MCP
authorization requires the access token in every HTTP request; no request
context is retained between requests.
"""

import dataclasses
import json
import logging
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

# ContextVar holding the authenticated UserContext for the current request.
_mcp_user_context_var: ContextVar[Any] = ContextVar("mcp_user_context")

# MCP JSON-RPC methods that are allowed without authentication.
_UNAUTHENTICATED_METHODS = frozenset({"initialize", "ping"})

# ASGI scope key a mount sets to name the resource it serves (RFC 9728), e.g.
# ``mcp/clients/<client id>``. Absent for the plain ``/mcp`` mount, whose
# resource is the one the root metadata document already describes.
PROTECTED_RESOURCE_SCOPE_KEY = "agentarea_protected_resource"

# ASGI scope key holding the workspace reference a pinned mount's URL names
# (``/mcp/w/<slug>``). Absent on the bare ``/mcp`` mount, where each
# workspace-scoped tool takes a required ``workspace`` argument instead.
WORKSPACE_SCOPE_KEY = "agentarea_workspace"

# What a URL may name as a workspace: a slug or a workspace id.
WORKSPACE_REFERENCE_PATTERN = re.compile(
    r"[a-z0-9-]{1,120}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


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


class WorkspaceAccessDeniedError(PermissionError):
    """The caller named a workspace that does not exist or they cannot reach."""


@asynccontextmanager
async def bind_workspace(reference: str) -> AsyncIterator[None]:
    """Run the enclosed tool call against the workspace *reference* names.

    *reference* is a workspace id or slug. It goes through the same resolver and
    membership gate as the REST surface, so an unknown workspace and a foreign
    one are refused alike. The bound context is a copy: the authenticated one
    may be shared by concurrent calls naming different workspaces.
    """
    from agentarea_common.auth.dependencies import (
        _apply_workspace_override,
        _resolve_workspace_reference,
    )
    from fastapi import HTTPException

    caller = get_mcp_user_context()
    bound = dataclasses.replace(caller)
    workspace_id = await _resolve_workspace_reference(bound, reference)
    if workspace_id is None:
        raise WorkspaceAccessDeniedError(f"No accessible workspace '{reference}'")
    try:
        _apply_workspace_override(bound, workspace_id)
    except HTTPException:
        raise WorkspaceAccessDeniedError(f"No accessible workspace '{reference}'") from None

    token = _mcp_user_context_var.set(bound)
    try:
        yield
    finally:
        _mcp_user_context_var.reset(token)


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


def _www_authenticate_header(resource_path: str | None = None) -> str:
    """RFC 9728 WWW-Authenticate header for OAuth protected-resource discovery.

    *resource_path* names the resource being protected (e.g.
    ``client-mcp/<client id>``) so the client is sent to the document that
    describes **that** resource. Pointing every mount at the root document
    hands a client metadata whose ``resource`` disagrees with the URL it called,
    and RFC 9728 §3.3 requires it to reject exactly that.
    """
    try:
        from agentarea_common.config import get_settings

        api_base = get_settings().app.API_BASE_URL.rstrip("/")
        location = f"{api_base}/.well-known/oauth-protected-resource"
        if resource_path:
            location = f"{location}/{resource_path.strip('/')}"
        return f'Bearer resource_metadata="{location}"'
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

    Allows only legacy handshake methods (``initialize``, ``ping`` and
    ``notifications/*``) without auth.  Modern ``server/discover`` requests
    are protected because MCP authorization requires an access token on every
    HTTP request.  Every other method requires a valid Bearer token on the
    same request.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

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
        auth_header = request.headers.get("authorization", "")

        token = _mcp_user_context_var.set(None)
        pinned_workspace = scope.get(WORKSPACE_SCOPE_KEY)
        workspace_denied = False

        try:
            # ---------- attempt authentication ----------
            if auth_header.lower().startswith("bearer "):
                bearer_token = auth_header[len("bearer ") :]
                workspace_denied = await self._try_authenticate(
                    bearer_token, request, pinned_workspace
                )

            # ---------- gate: reject protected methods without auth ----------
            ctx = _mcp_user_context_var.get(None)
            if ctx is None and workspace_denied and not _is_handshake_method(method):
                # Authenticated, but not for this workspace: re-running OAuth
                # would mint the same token, so this must not be a 401.
                await _send_workspace_denied(send, request_id, pinned_workspace)
                return
            if ctx is None and not _is_handshake_method(method):
                logger.info("MCP auth: rejecting unauthenticated request method=%s", method)
                await _send_401(send, request_id, scope.get(PROTECTED_RESOURCE_SCOPE_KEY))
                return

            # ---------- forward to downstream handler ----------
            await self.app(scope, _make_replay_receive(body), send)
        finally:
            _mcp_user_context_var.reset(token)

    async def _try_authenticate(
        self, bearer_token: str, request: Request, pinned_workspace: str | None = None
    ) -> bool:
        """Attempt to validate the token and set UserContext. Never raises.

        *pinned_workspace* is the workspace the mount's URL names, if any.
        Returns True when the token is valid but that workspace is not
        reachable for its principal (the context is then left unset).
        """
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
                    if not await _select_workspace(user_context, pinned_workspace):
                        return True
                    _mcp_user_context_var.set(user_context)
                    return False

            # --- JWT path (Kratos then Hydra) ---
            auth_provider = get_auth_provider()
            auth_result = await auth_provider.verify_token(bearer_token)

            if auth_result.is_authenticated and auth_result.token:
                # Start on the caller's own workspace; an explicit workspace
                # reference is applied only after the membership check below.
                user_context = UserContext(
                    user_id=auth_result.token.user_id,
                    workspace_id=auth_result.token.user_id,
                    email=auth_result.token.email,
                )
                await _resolve_accessible_workspaces(user_context)
                if not await _select_workspace(user_context, pinned_workspace):
                    return True
                _mcp_user_context_var.set(user_context)
                return False

            # Kratos failed — try Hydra OAuth
            hydra_context = await _try_hydra_token(bearer_token, request)
            if hydra_context is not None:
                await _resolve_accessible_workspaces(hydra_context)
                if not await _select_workspace(hydra_context, pinned_workspace):
                    return True
                _mcp_user_context_var.set(hydra_context)
                return False

            logger.debug("MCP auth: token validation failed (no provider accepted)")
            return False

        except Exception:
            logger.debug("MCP auth: token validation error", exc_info=True)
            return False


# ---------------------------------------------------------------------------
# Helpers (module-level for testability)
# ---------------------------------------------------------------------------


async def _select_workspace(user_context: Any, pinned_workspace: str | None) -> bool:
    """Apply the workspace a pinned mount names, reusing the REST guard.

    `/mcp` is a second authentication path alongside the `/v1` router. It must
    not re-implement the membership check, or the two drift and only one of them
    gets hardened.

    Returns False when the URL names a workspace the caller cannot reach; the
    caller then leaves the context unset so the request fails closed. With no
    pinned workspace nothing is selected here: the bare mount binds one per tool
    call from the required ``workspace`` argument.
    """
    if pinned_workspace is None:
        return True

    from agentarea_common.auth.dependencies import (
        _apply_workspace_override,
        _resolve_workspace_reference,
    )

    try:
        workspace_id = await _resolve_workspace_reference(user_context, pinned_workspace)
        if workspace_id is None:
            raise LookupError(pinned_workspace)
        _apply_workspace_override(user_context, workspace_id)
        return True
    except Exception:
        logger.warning(
            "MCP auth: rejected pinned workspace user=%s requested=%s accessible=%s",
            user_context.user_id,
            pinned_workspace,
            user_context.accessible_workspaces,
            exc_info=True,
        )
        return False


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


async def _send_workspace_denied(send: Send, request_id: Any, reference: str | None) -> None:
    """Send HTTP 403: authenticated, but the URL names a workspace out of reach.

    Unknown and foreign workspaces get the same message, so the response does
    not reveal which workspaces exist.
    """
    error_body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": f"No accessible workspace '{reference}'"},
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [[b"content-type", b"application/json"]],
        }
    )
    await send({"type": "http.response.body", "body": error_body})


async def _send_401(send: Send, request_id: Any, resource_path: str | None = None) -> None:
    """Send an HTTP 401 response with RFC 9728 WWW-Authenticate header."""
    www_auth = _www_authenticate_header(resource_path)
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
