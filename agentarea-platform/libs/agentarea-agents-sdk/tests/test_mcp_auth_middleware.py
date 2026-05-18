"""Unit tests for MCP auth middleware."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_agents_sdk.mcp_server.auth import MCPAuthMiddleware, _mcp_user_context_var
from agentarea_common.auth.context import UserContext


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
