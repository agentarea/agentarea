"""Unit tests for MCP auth middleware."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.auth.context import UserContext, UserPrincipal

from agentarea_agents_sdk.mcp_server.auth import (
    PROTECTED_RESOURCE_SCOPE_KEY,
    MCPAuthMiddleware,
    _mcp_user_context_var,
)

WORKSPACES = {
    "alice-workspace": SimpleNamespace(id="alice-workspace", slug="alice-workspace"),
    "shared-workspace": SimpleNamespace(id="shared-workspace", slug="shared-workspace"),
    "bob-workspace": SimpleNamespace(id="bob-workspace", slug="bob-workspace"),
}


async def _load_workspace(*, workspace_id=None, slug=None):
    return WORKSPACES.get(slug or workspace_id)


def _grant(*workspaces: str):
    """Stub _resolve_access that grants a fixed workspace set."""

    async def _resolve(principal: UserPrincipal, *, slug: str | None = None) -> None:
        principal.accessible_workspaces = list(workspaces)
        principal.admin_workspaces = []

    return AsyncMock(side_effect=_resolve)


@pytest.fixture(autouse=True)
def _workspace_rows():
    with patch("agentarea_common.workspaces.lookup.load_workspace", new=_load_workspace):
        yield


@pytest.mark.asyncio
async def test_mcp_auth_accepts_agentarea_pat_prefix():
    """AgentArea MCP PATs use the aat_ prefix and must enter API-key auth."""
    middleware = MCPAuthMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {}
    principal = UserPrincipal(user_id="user-1", bound_workspace_id="workspace-1")
    token = _mcp_user_context_var.set(None)

    try:
        with (
            patch(
                "agentarea_common.auth.dependencies._validate_api_key",
                new=AsyncMock(return_value=principal),
            ) as validate_api_key,
            patch("agentarea_common.auth.dependencies._resolve_access", new=_grant()),
            patch("agentarea_common.auth.dependencies.get_auth_provider") as get_auth_provider,
        ):
            auth_provider = MagicMock()
            auth_provider.verify_token = AsyncMock()
            get_auth_provider.return_value = auth_provider

            await middleware._try_authenticate("aat_valid-token", request)

        validate_api_key.assert_awaited_once_with("aat_valid-token", request)
        auth_provider.verify_token.assert_not_awaited()
        assert _mcp_user_context_var.get(None) is principal
    finally:
        _mcp_user_context_var.reset(token)


def _jwt_auth_result(user_id: str) -> MagicMock:
    auth_result = MagicMock()
    auth_result.is_authenticated = True
    auth_result.token = MagicMock()
    auth_result.token.user_id = user_id
    auth_result.token.email = None
    return auth_result


async def _authenticate_jwt(
    request, *, granted: tuple[str, ...], pinned: str | None = None
) -> UserContext | UserPrincipal | None:
    """Run the JWT path of the middleware with a stubbed provider and grant set."""
    middleware = MCPAuthMiddleware(MagicMock())
    token = _mcp_user_context_var.set(None)
    try:
        with (
            patch("agentarea_common.auth.dependencies._resolve_access", new=_grant(*granted)),
            patch("agentarea_common.auth.dependencies.get_auth_provider") as get_auth_provider,
        ):
            auth_provider = MagicMock()
            auth_provider.verify_token = AsyncMock(return_value=_jwt_auth_result("alice"))
            get_auth_provider.return_value = auth_provider

            await middleware._try_authenticate("jwt-token", request, pinned)
        return _mcp_user_context_var.get(None)
    finally:
        _mcp_user_context_var.reset(token)


async def _authenticate_hydra(
    request, *, granted: tuple[str, ...], pinned: str | None = None
) -> UserContext | UserPrincipal | None:
    """Run the Hydra fallback path with a fixed OAuth subject and grant set."""
    middleware = MCPAuthMiddleware(MagicMock())
    token = _mcp_user_context_var.set(None)
    rejected = MagicMock(is_authenticated=False, token=None)
    try:
        with (
            patch("agentarea_common.auth.dependencies._resolve_access", new=_grant(*granted)),
            patch(
                "agentarea_common.auth.dependencies._try_hydra_token",
                new=AsyncMock(return_value=UserPrincipal(user_id="alice")),
            ),
            patch("agentarea_common.auth.dependencies.get_auth_provider") as get_auth_provider,
        ):
            auth_provider = MagicMock()
            auth_provider.verify_token = AsyncMock(return_value=rejected)
            get_auth_provider.return_value = auth_provider

            await middleware._try_authenticate("hydra-token", request, pinned)
        return _mcp_user_context_var.get(None)
    finally:
        _mcp_user_context_var.reset(token)


class TestPinnedWorkspaceIsAuthorized:
    """`/mcp/w/<workspace>` must not serve a workspace the caller cannot reach.

    The REST router enforces membership when it enters the workspace the path
    names; the MCP middleware is a separate auth path and must reuse that gate,
    or any authenticated user could read another workspace by editing the URL.
    """

    @pytest.mark.asyncio
    async def test_foreign_pinned_workspace_is_rejected(self):
        request = MagicMock()
        request.headers = {}

        context = await _authenticate_jwt(
            request, granted=("alice-workspace",), pinned="bob-workspace"
        )

        # Fail closed: no context at all, rather than a context on Bob's workspace.
        assert context is None

    @pytest.mark.asyncio
    async def test_member_pinned_workspace_is_applied(self):
        request = MagicMock()
        request.headers = {}

        context = await _authenticate_jwt(
            request, granted=("alice-workspace", "shared-workspace"), pinned="shared-workspace"
        )

        assert isinstance(context, UserContext)
        assert context.user_id == "alice"
        assert context.workspace_id == "shared-workspace"
        assert context.workspace_slug == "shared-workspace"

    @pytest.mark.asyncio
    async def test_workspace_header_selects_nothing(self):
        """The URL is the only selector: a header naming a member workspace is ignored."""
        request = MagicMock()
        request.headers = {"X-AgentArea-Workspace": "shared-workspace"}

        caller = await _authenticate_jwt(request, granted=("alice-workspace", "shared-workspace"))

        assert isinstance(caller, UserPrincipal)
        assert not hasattr(caller, "workspace_id")

    @pytest.mark.asyncio
    async def test_api_key_path_also_rejects_foreign_pinned_workspace(self):
        middleware = MCPAuthMiddleware(MagicMock())
        request = MagicMock()
        request.headers = {}
        issued_for = UserPrincipal(user_id="alice", bound_workspace_id="alice-workspace")
        token = _mcp_user_context_var.set(None)

        try:
            with (
                patch(
                    "agentarea_common.auth.dependencies._validate_api_key",
                    new=AsyncMock(return_value=issued_for),
                ),
                patch(
                    "agentarea_common.auth.dependencies._resolve_access",
                    new=_grant("alice-workspace"),
                ),
                patch("agentarea_common.auth.dependencies.get_auth_provider"),
            ):
                await middleware._try_authenticate("aat_key", request, "bob-workspace")

            assert _mcp_user_context_var.get(None) is None
        finally:
            _mcp_user_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_hydra_member_pinned_workspace_is_applied(self):
        request = MagicMock()
        request.headers = {}

        context = await _authenticate_hydra(
            request, granted=("alice-workspace", "shared-workspace"), pinned="shared-workspace"
        )

        assert context is not None
        assert context.workspace_id == "shared-workspace"

    @pytest.mark.asyncio
    async def test_hydra_foreign_pinned_workspace_is_rejected(self):
        request = MagicMock()
        request.headers = {}

        context = await _authenticate_hydra(
            request, granted=("alice-workspace",), pinned="no-such-workspace"
        )

        assert context is None


class TestUnauthenticatedChallenge:
    """Where the 401 sends a client to discover OAuth (RFC 9728).

    Every mount used to advertise the root metadata document, whose ``resource``
    is ``<API>/mcp``. A harness that follows §3.3 compares that against the URL
    it called and refuses when they disagree — which is exactly what
    ``codex mcp login`` does against ``/client-mcp/<id>``.
    """

    @staticmethod
    async def _challenge(scope_extra: dict) -> str:
        sent: list[dict] = []

        async def receive():
            return {
                "type": "http.request",
                "body": b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                "more_body": False,
            }

        async def send(message):
            sent.append(message)

        settings = MagicMock()
        settings.app.API_BASE_URL = "https://api.example.com"
        middleware = MCPAuthMiddleware(AsyncMock())

        with patch("agentarea_common.config.get_settings", return_value=settings):
            await middleware(
                {"type": "http", "path": "/", "headers": [], **scope_extra},
                receive,
                send,
            )

        start = next(m for m in sent if m["type"] == "http.response.start")
        assert start["status"] == 401
        return next(value.decode() for key, value in start["headers"] if key == b"www-authenticate")

    @pytest.mark.asyncio
    async def test_client_mcp_points_at_its_own_metadata(self):
        challenge = await self._challenge(
            {PROTECTED_RESOURCE_SCOPE_KEY: "client-mcp/74dfa41a-1736-4ab1-a470-2e2d4c4e56c8"}
        )

        assert challenge == (
            'Bearer resource_metadata="https://api.example.com/.well-known/'
            'oauth-protected-resource/client-mcp/74dfa41a-1736-4ab1-a470-2e2d4c4e56c8"'
        )

    @pytest.mark.asyncio
    async def test_plain_mcp_mount_keeps_the_root_location(self):
        challenge = await self._challenge({})

        assert challenge == (
            'Bearer resource_metadata="https://api.example.com/.well-known/'
            'oauth-protected-resource"'
        )


@pytest.mark.asyncio
async def test_each_protected_request_requires_its_own_bearer_token():
    responses: list[dict] = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = MCPAuthMiddleware(inner)

    async def authenticate(_token, _request, _pinned_workspace=None):
        _mcp_user_context_var.set(UserPrincipal(user_id="alice"))
        return False

    async def request(headers: list[tuple[bytes, bytes]]):
        responses.clear()

        async def receive():
            return {
                "type": "http.request",
                "body": b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
                "more_body": False,
            }

        async def send(message):
            responses.append(message)

        await middleware(
            {"type": "http", "path": "/", "headers": headers},
            receive,
            send,
        )
        return list(responses)

    with patch.object(
        middleware, "_try_authenticate", side_effect=authenticate
    ) as authenticate_mock:
        first = await request([(b"authorization", b"Bearer first-token")])
        second = await request([])

    assert (
        next(message for message in first if message["type"] == "http.response.start")["status"]
        == 200
    )
    assert (
        next(message for message in second if message["type"] == "http.response.start")["status"]
        == 401
    )
    authenticate_mock.assert_awaited_once()
