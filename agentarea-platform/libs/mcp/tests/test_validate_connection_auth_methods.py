"""Auth-method detection on `validate_connection`.

The create-connection page validates the bare endpoint on load. When the
server answers 401/403 the response carries `auth_methods`, so the page can
render OAuth / manual-credentials up front instead of after an instance has
already been created.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from agentarea_mcp.application.service import MCPServerInstanceService


def _service() -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        return MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=MagicMock(),
        )


def _client_returning(status_code: int, headers: dict[str, str] | None = None):
    """Patch httpx.AsyncClient so `async with` yields a client whose GET answers once."""
    resp = MagicMock(status_code=status_code, headers=httpx.Headers(headers or {}))
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return patch("agentarea_mcp.application.service.httpx.AsyncClient", return_value=client)


class TestDetectAuthMethods:
    @pytest.mark.asyncio
    async def test_open_endpoint(self):
        with _client_returning(200):
            assert await _service()._detect_auth_methods("https://8.8.8.8/mcp") == ["none"]

    @pytest.mark.asyncio
    async def test_oauth_when_discovery_succeeds(self):
        oauth = MagicMock()
        oauth.discover_auth_server = AsyncMock(return_value=MagicMock())
        with (
            _client_returning(401, {"www-authenticate": 'Bearer resource_metadata="https://x"'}),
            patch("agentarea_mcp.application.service.MCPOAuthClientService", return_value=oauth),
        ):
            methods = await _service()._detect_auth_methods("https://8.8.8.8/mcp")
        assert methods == ["oauth", "credentials"]

    @pytest.mark.asyncio
    async def test_credentials_when_no_bearer_challenge(self):
        with _client_returning(403):
            assert await _service()._detect_auth_methods("https://8.8.8.8/mcp") == ["credentials"]

    @pytest.mark.asyncio
    async def test_unreachable_endpoint_is_unclassified(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch("agentarea_mcp.application.service.httpx.AsyncClient", return_value=client):
            assert await _service()._detect_auth_methods("https://8.8.8.8/mcp") == []


class TestValidateConnectionReportsAuthMethods:
    @pytest.mark.asyncio
    async def test_401_carries_auth_methods(self):
        service = _service()
        with (
            patch.object(
                service, "_list_tools_via_mcp", new=AsyncMock(side_effect=Exception("HTTP 401"))
            ),
            patch.object(
                service,
                "_detect_auth_methods",
                new=AsyncMock(return_value=["oauth", "credentials"]),
            ) as detect,
        ):
            result = await service.validate_connection(url="https://8.8.8.8/mcp")

        assert result["valid"] is False
        assert result["auth_methods"] == ["oauth", "credentials"]
        detect.assert_awaited_once_with("https://8.8.8.8/mcp")

    @pytest.mark.asyncio
    async def test_masked_401_is_still_reported_as_auth_failure(self):
        """Streamable HTTP 401 hidden behind the SSE fallback's 404."""
        service = _service()
        with (
            patch.object(
                service,
                "_list_tools_via_mcp",
                new=AsyncMock(side_effect=Exception("Client error '404 Not Found' for url '/sse'")),
            ),
            patch.object(
                service, "_detect_auth_methods", new=AsyncMock(return_value=["credentials"])
            ),
        ):
            result = await service.validate_connection(url="https://8.8.8.8/mcp")

        assert result["valid"] is False
        assert result["auth_methods"] == ["credentials"]
        assert "Authentication failed" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_unreachable_endpoint_stays_a_connection_error(self):
        service = _service()
        with (
            patch.object(
                service, "_list_tools_via_mcp", new=AsyncMock(side_effect=Exception("timeout"))
            ),
            patch.object(service, "_detect_auth_methods", new=AsyncMock(return_value=[])),
        ):
            result = await service.validate_connection(url="https://8.8.8.8/mcp")

        assert result["valid"] is False
        assert "auth_methods" not in result
        assert "Connection failed" in result["errors"][0]
