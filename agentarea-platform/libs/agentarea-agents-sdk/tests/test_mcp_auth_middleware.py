"""Unit tests for MCP auth middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_common.auth.context import UserContext

from agentarea_agents_sdk.mcp_server.auth import (
    PROTECTED_RESOURCE_SCOPE_KEY,
    MCPAuthMiddleware,
    _mcp_user_context_var,
)


@pytest.mark.asyncio
async def test_mcp_auth_accepts_agentarea_pat_prefix():
    """AgentArea MCP PATs use the aat_ prefix and must enter API-key auth."""
    middleware = MCPAuthMiddleware(MagicMock())
    request = MagicMock()
    request.headers = {}
    user_context = UserContext(user_id="user-1", workspace_id="workspace-1")
    token = _mcp_user_context_var.set(None)

    try:
        with (
            patch(
                "agentarea_common.auth.dependencies._validate_api_key",
                new=AsyncMock(return_value=user_context),
            ) as validate_api_key,
            patch(
                "agentarea_common.auth.dependencies._resolve_accessible_workspaces",
                new=AsyncMock(),
            ),
            patch("agentarea_common.auth.dependencies.get_auth_provider") as get_auth_provider,
        ):
            auth_provider = MagicMock()
            auth_provider.verify_token = AsyncMock()
            get_auth_provider.return_value = auth_provider

            await middleware._try_authenticate("aat_valid-token", request)

        validate_api_key.assert_awaited_once_with("aat_valid-token", request)
        auth_provider.verify_token.assert_not_awaited()
        assert _mcp_user_context_var.get(None) is user_context
    finally:
        _mcp_user_context_var.reset(token)


def _grant(*workspaces: str):
    """Stub _resolve_accessible_workspaces that grants a fixed workspace set."""

    async def _resolve(user_context: UserContext) -> None:
        user_context.accessible_workspaces = list(workspaces)

    return AsyncMock(side_effect=_resolve)


def _jwt_auth_result(user_id: str) -> MagicMock:
    auth_result = MagicMock()
    auth_result.is_authenticated = True
    auth_result.token = MagicMock()
    auth_result.token.user_id = user_id
    return auth_result


async def _authenticate_jwt(request, *, granted: tuple[str, ...]) -> UserContext | None:
    """Run the JWT path of the middleware with a stubbed provider and grant set."""
    middleware = MCPAuthMiddleware(MagicMock())
    token = _mcp_user_context_var.set(None)
    try:
        with (
            patch(
                "agentarea_common.auth.dependencies._resolve_accessible_workspaces",
                new=_grant(*granted),
            ),
            patch("agentarea_common.auth.dependencies.get_auth_provider") as get_auth_provider,
        ):
            auth_provider = MagicMock()
            auth_provider.verify_token = AsyncMock(return_value=_jwt_auth_result("alice"))
            get_auth_provider.return_value = auth_provider

            await middleware._try_authenticate("jwt-token", request)
        return _mcp_user_context_var.get(None)
    finally:
        _mcp_user_context_var.reset(token)


async def _authenticate_hydra(request, *, granted: tuple[str, ...]) -> UserContext | None:
    """Run the Hydra fallback path with a fixed OAuth subject and grant set."""
    middleware = MCPAuthMiddleware(MagicMock())
    token = _mcp_user_context_var.set(None)
    hydra_context = UserContext(user_id="alice", workspace_id="alice")
    rejected = MagicMock(is_authenticated=False, token=None)
    try:
        with (
            patch(
                "agentarea_common.auth.dependencies._resolve_accessible_workspaces",
                new=_grant(*granted),
            ),
            patch(
                "agentarea_common.auth.dependencies._try_hydra_token",
                new=AsyncMock(return_value=hydra_context),
            ),
            patch("agentarea_common.auth.dependencies.get_auth_provider") as get_auth_provider,
        ):
            auth_provider = MagicMock()
            auth_provider.verify_token = AsyncMock(return_value=rejected)
            get_auth_provider.return_value = auth_provider

            await middleware._try_authenticate("hydra-token", request)
        return _mcp_user_context_var.get(None)
    finally:
        _mcp_user_context_var.reset(token)


class TestMCPWorkspaceOverrideIsAuthorized:
    """`/mcp` must not accept an X-Workspace-ID the caller is not a member of.

    The REST router enforces this through `_apply_workspace_selection`; the MCP
    middleware is a separate auth path, and when it skipped that check any
    authenticated user could read another workspace by setting the header.
    """

    @pytest.mark.asyncio
    async def test_foreign_workspace_header_is_rejected(self):
        request = MagicMock()
        request.headers = {"X-Workspace-ID": "bob-workspace"}

        context = await _authenticate_jwt(request, granted=("alice",))

        # Fail closed: no context at all, rather than a context on Bob's workspace.
        assert context is None

    @pytest.mark.asyncio
    async def test_member_workspace_header_is_applied(self):
        request = MagicMock()
        request.headers = {"X-Workspace-ID": "shared-workspace"}

        context = await _authenticate_jwt(request, granted=("alice", "shared-workspace"))

        assert context is not None
        assert context.user_id == "alice"
        assert context.workspace_id == "shared-workspace"

    @pytest.mark.asyncio
    async def test_without_header_defaults_to_own_workspace(self):
        request = MagicMock()
        request.headers = {}

        context = await _authenticate_jwt(request, granted=("alice",))

        assert context is not None
        assert context.workspace_id == "alice"

    @pytest.mark.asyncio
    async def test_api_key_path_also_rejects_foreign_workspace(self):
        """_validate_api_key deliberately ignores the header; the caller must check it."""
        middleware = MCPAuthMiddleware(MagicMock())
        request = MagicMock()
        request.headers = {"X-Workspace-ID": "bob-workspace"}
        issued_for = UserContext(user_id="alice", workspace_id="alice-workspace")
        token = _mcp_user_context_var.set(None)

        try:
            with (
                patch(
                    "agentarea_common.auth.dependencies._validate_api_key",
                    new=AsyncMock(return_value=issued_for),
                ),
                patch(
                    "agentarea_common.auth.dependencies._resolve_accessible_workspaces",
                    new=_grant("alice-workspace"),
                ),
                patch("agentarea_common.auth.dependencies.get_auth_provider"),
            ):
                await middleware._try_authenticate("aat_key", request)

            assert _mcp_user_context_var.get(None) is None
        finally:
            _mcp_user_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_hydra_member_workspace_header_is_applied(self):
        request = MagicMock()
        request.headers = {"X-AgentArea-Workspace": "shared-workspace"}

        context = await _authenticate_hydra(
            request,
            granted=("alice", "shared-workspace"),
        )

        assert context is not None
        assert context.workspace_id == "shared-workspace"

    @pytest.mark.asyncio
    async def test_hydra_foreign_workspace_header_is_rejected(self):
        request = MagicMock()
        request.headers = {"X-Workspace-ID": "bob-workspace"}

        context = await _authenticate_hydra(request, granted=("alice",))

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
