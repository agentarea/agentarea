"""Tests for OpenAPIConnectionService."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_openapi.domain.models import OpenAPIConnection


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List users",
            }
        }
    },
}


class TestDiscoverTools:
    @pytest.fixture
    def service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        return OpenAPIConnectionService(repository_factory=mock_factory)

    @pytest.mark.asyncio
    async def test_discover_from_spec_content(self, service):
        """If connection has spec_content, parse it directly."""
        conn = OpenAPIConnection(
            name="Test",
            base_url="https://api.example.com",
            spec_content=SAMPLE_SPEC,
        )
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = conn

        result = await service.discover_tools(conn.id)

        assert result["tools_discovered"] == 1
        assert result["tools"][0]["name"] == "listUsers"

    @pytest.mark.asyncio
    async def test_discover_from_spec_url(self, service):
        """If connection has spec_url but no content, fetch it."""
        conn = OpenAPIConnection(
            name="Test",
            base_url="https://api.example.com",
            spec_url="https://api.example.com/openapi.json",
        )
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = conn

        with patch("agentarea_openapi.application.service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.text = json.dumps(SAMPLE_SPEC)
            mock_resp.raise_for_status = lambda: None
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.discover_tools(conn.id)

        assert result["tools_discovered"] == 1

    @pytest.mark.asyncio
    async def test_discover_no_spec(self, service):
        """If no spec_url or spec_content, raise ValueError."""
        conn = OpenAPIConnection(
            name="Test",
            base_url="https://api.example.com",
        )
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = conn

        with pytest.raises(ValueError, match="No spec"):
            await service.discover_tools(conn.id)

    @pytest.mark.asyncio
    async def test_discover_not_found(self, service):
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.discover_tools("nonexistent-id")
