"""Auth-method detection on `validate_connection`.

The create-connection page validates the bare endpoint on load. When the
server answers 401/403 the response carries `auth_methods`, so the page can
render OAuth / manual-credentials up front instead of after an instance has
already been created.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from agentarea_mcp.application.oauth_client_service import OAuthCapability
from agentarea_mcp.application.service import MCPServerInstanceService

URL = "https://8.8.8.8/mcp"
SERVER_ID = str(uuid4())


def _service(spec_url: str | None = URL) -> MCPServerInstanceService:
    """Service with a catalog lookup that resolves SERVER_ID to a spec at ``spec_url``."""
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        service = MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=MagicMock(),
        )
    spec = MagicMock(remote_url=spec_url) if spec_url is not None else None
    service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=spec)
    return service


def _client_returning(status_code: int, headers: dict[str, str] | None = None):
    """Patch the outbound client so `async with` yields a client whose GET answers once."""
    resp = MagicMock(status_code=status_code, headers=httpx.Headers(headers or {}))
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return patch("agentarea_mcp.application.service.safe_async_client", return_value=client)


def _oauth(status: str):
    """Patch the one OAuth classifier the detector reads."""
    oauth = MagicMock()
    oauth.assess = AsyncMock(return_value=OAuthCapability(status=status))  # type: ignore[arg-type]
    return patch("agentarea_mcp.application.service.MCPOAuthClientService", return_value=oauth)


class TestDetectAuthMethods:
    @pytest.mark.asyncio
    async def test_open_endpoint(self):
        with _client_returning(200), _oauth("unsupported"):
            assert await _service()._detect_auth_methods(URL) == ["none"]

    @pytest.mark.asyncio
    async def test_oauth_when_discovery_succeeds(self):
        with (
            _client_returning(401, {"www-authenticate": 'Bearer resource_metadata="https://x"'}),
            _oauth("ready"),
        ):
            methods = await _service()._detect_auth_methods(URL)
        assert methods == ["oauth", "credentials"]

    @pytest.mark.asyncio
    async def test_oauth_is_read_from_metadata_not_from_the_get_status(self):
        """Gmail's MCP is POST-only (405 on GET) and lists tools without a token,
        yet publishes RFC 9728 metadata and rejects every tool call without one.
        A status-code classifier called it open; the metadata says otherwise."""
        with _client_returning(405), _oauth("oauth_app_required") as oauth_cls:
            methods = await _service()._detect_auth_methods(URL)

        assert methods == ["oauth", "credentials"]
        oauth_cls.return_value.assess.assert_awaited_once_with(URL)

    @pytest.mark.asyncio
    async def test_credentials_when_no_bearer_challenge(self):
        with _client_returning(403), _oauth("unsupported"):
            assert await _service()._detect_auth_methods(URL) == ["credentials"]

    @pytest.mark.asyncio
    async def test_unreachable_endpoint_is_unclassified(self):
        client = MagicMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with (
            patch("agentarea_mcp.application.service.safe_async_client", return_value=client),
            _oauth("unsupported"),
        ):
            assert await _service()._detect_auth_methods(URL) == []


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
            result = await service.validate_connection(url=URL, server_id=SERVER_ID)

        assert result["valid"] is False
        assert result["auth_methods"] == ["oauth", "credentials"]
        detect.assert_awaited_once_with(URL)

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
            result = await service.validate_connection(url=URL, server_id=SERVER_ID)

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
            result = await service.validate_connection(url=URL, server_id=SERVER_ID)

        assert result["valid"] is False
        assert "auth_methods" not in result
        assert "Connection failed" in result["errors"][0]


class TestOpenListingStillReportsOAuth:
    """A server that lists tools without a token can still require one to call them."""

    @pytest.mark.asyncio
    async def test_successful_listing_carries_oauth_methods(self):
        service = _service()
        with (
            patch.object(
                service,
                "_list_tools_via_mcp",
                new=AsyncMock(return_value=MagicMock(tools=[])),
            ),
            patch.object(
                service,
                "_detect_auth_methods",
                new=AsyncMock(return_value=["oauth", "credentials"]),
            ),
        ):
            result = await service.validate_connection(url=URL, server_id=SERVER_ID)

        assert result["valid"] is True
        assert result["auth_methods"] == ["oauth", "credentials"]

    @pytest.mark.asyncio
    async def test_successful_listing_of_an_open_server_stays_plain(self):
        service = _service()
        with (
            patch.object(
                service,
                "_list_tools_via_mcp",
                new=AsyncMock(return_value=MagicMock(tools=[])),
            ),
            patch.object(service, "_detect_auth_methods", new=AsyncMock(return_value=["none"])),
        ):
            result = await service.validate_connection(url=URL, server_id=SERVER_ID)

        assert result["valid"] is True
        assert "auth_methods" not in result

    @pytest.mark.asyncio
    async def test_validating_entered_credentials_skips_detection(self):
        """Once the user has typed a header in, the question is whether it works."""
        service = _service()
        with (
            patch.object(
                service,
                "_list_tools_via_mcp",
                new=AsyncMock(return_value=MagicMock(tools=[])),
            ),
            patch.object(service, "_detect_auth_methods", new=AsyncMock()) as detect,
        ):
            result = await service.validate_connection(
                url=URL, headers={"Authorization": "Bearer t"}, server_id=SERVER_ID
            )

        assert result["valid"] is True
        detect.assert_not_awaited()


class TestDetectionIsScopedToCatalogSpecs:
    """The probe dials only an endpoint stored on a catalog spec, never the raw input."""

    @pytest.mark.asyncio
    async def test_no_server_id_skips_detection(self):
        service = _service()
        with (
            patch.object(
                service, "_list_tools_via_mcp", new=AsyncMock(side_effect=Exception("HTTP 401"))
            ),
            patch.object(service, "_detect_auth_methods", new=AsyncMock()) as detect,
        ):
            result = await service.validate_connection(url=URL)

        detect.assert_not_awaited()
        assert result["valid"] is False
        assert result["auth_methods"] == []

    @pytest.mark.asyncio
    async def test_url_differing_from_spec_endpoint_skips_detection(self):
        service = _service(spec_url="https://1.1.1.1/mcp")
        with (
            patch.object(
                service, "_list_tools_via_mcp", new=AsyncMock(side_effect=Exception("HTTP 401"))
            ),
            patch.object(service, "_detect_auth_methods", new=AsyncMock()) as detect,
        ):
            await service.validate_connection(url=URL, server_id=SERVER_ID)

        detect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_spec_skips_detection(self):
        service = _service(spec_url=None)
        with (
            patch.object(
                service, "_list_tools_via_mcp", new=AsyncMock(side_effect=Exception("HTTP 401"))
            ),
            patch.object(service, "_detect_auth_methods", new=AsyncMock()) as detect,
        ):
            await service.validate_connection(url=URL, server_id=SERVER_ID)

        detect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_probe_uses_the_stored_endpoint(self):
        service = _service()
        with (
            patch.object(
                service, "_list_tools_via_mcp", new=AsyncMock(side_effect=Exception("HTTP 401"))
            ),
            patch.object(
                service, "_detect_auth_methods", new=AsyncMock(return_value=["credentials"])
            ) as detect,
        ):
            await service.validate_connection(url=URL, server_id=SERVER_ID)

        service.mcp_server_repository.get_server_by_id.assert_awaited_once_with(SERVER_ID)
        detect.assert_awaited_once_with(URL)


def _probing(service: MCPServerInstanceService, url: str = URL) -> MCPServerInstanceService:
    """Point probe_instance_auth at one URL-type instance at ``url``."""
    service.repository = MagicMock()
    service.repository.get_by_id = AsyncMock(
        return_value=MagicMock(id="inst-1", server_spec_id=None)
    )
    service._get_transport_spec_for_instance = AsyncMock(  # type: ignore[method-assign]
        return_value={"type": "url", "endpoint_url": url}
    )
    return service


class TestProbeInstanceAuth:
    """The per-instance probe answers from the same classifier as the create page."""

    @pytest.mark.asyncio
    async def test_a_server_that_lists_openly_but_advertises_oauth_requires_auth(self):
        """Gmail: 405 on GET, tools/list without a token, 401 on every call.
        The probe used to report it open because it only read the GET status."""
        with _client_returning(405), _oauth("oauth_app_required"):
            result = await _probing(_service()).probe_instance_auth("inst-1")

        assert result == {"status": "auth_required", "methods": ["oauth", "credentials"]}

    @pytest.mark.asyncio
    async def test_an_open_server_is_ok(self):
        with _client_returning(200), _oauth("unsupported"):
            result = await _probing(_service()).probe_instance_auth("inst-1")

        assert result == {"status": "ok", "methods": ["none"]}

    @pytest.mark.asyncio
    async def test_a_challenge_without_oauth_asks_for_credentials(self):
        with _client_returning(401), _oauth("unsupported"):
            result = await _probing(_service()).probe_instance_auth("inst-1")

        assert result["status"] == "auth_required"
        assert result["methods"] == ["credentials"]

    @pytest.mark.asyncio
    async def test_the_oauth_classifier_never_dials_a_refused_address(self):
        with _oauth("ready") as oauth_cls:
            result = await _probing(
                _service(), "http://169.254.169.254/latest/meta-data/"
            ).probe_instance_auth("inst-1")

        assert result["status"] == "error"
        oauth_cls.return_value.assess.assert_not_awaited()
