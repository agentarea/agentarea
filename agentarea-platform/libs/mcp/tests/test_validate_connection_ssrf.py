"""SSRF guard on MCP connection validation.

`POST /v1/mcp-server-instances/validate-connection` takes a URL from the request
body and returns the upstream tool list to the caller, so an unguarded sink is a
full-read SSRF, not a blind one: any authenticated user could enumerate internal
services and read cloud metadata through it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentarea_mcp.application.service import MCPServerInstanceService


def _service() -> MCPServerInstanceService:
    with patch("agentarea_mcp.application.service.get_database", MagicMock()):
        return MCPServerInstanceService(
            repository_factory=MagicMock(),
            event_broker=MagicMock(),
            secret_manager=MagicMock(),
        )


class TestValidateConnectionRefusesNonPublicTargets:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000/mcp",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.5/mcp",
            "http://[::1]:8000/mcp",
            "file:///etc/passwd",
            "gopher://127.0.0.1:6379/_INFO",
        ],
    )
    async def test_rejects_and_never_dials(self, url: str):
        service = _service()

        with patch.object(service, "_list_tools_via_mcp", new=AsyncMock()) as dial:
            result = await service.validate_connection(url=url)

        assert result["valid"] is False
        assert result["errors"]
        # The request must not be issued at all — a refused-after-dial guard
        # would still leak timing and still hit the internal service.
        dial.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_public_target_still_works(self):
        service = _service()
        listing = MagicMock()
        listing.tools = []

        with patch.object(
            service, "_list_tools_via_mcp", new=AsyncMock(return_value=listing)
        ) as dial:
            # IP literal so the guard has nothing to resolve and the test stays offline.
            result = await service.validate_connection(url="https://8.8.8.8/mcp")

        assert result["valid"] is True
        dial.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_url_is_still_rejected(self):
        service = _service()

        with patch.object(service, "_list_tools_via_mcp", new=AsyncMock()) as dial:
            result = await service.validate_connection(url="")

        assert result["valid"] is False
        dial.assert_not_awaited()
