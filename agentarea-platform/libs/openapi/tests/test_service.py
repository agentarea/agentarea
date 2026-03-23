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

        with patch(
            "agentarea_openapi.application.service.fetch_and_parse_spec",
            new_callable=AsyncMock,
            return_value=SAMPLE_SPEC,
        ):
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


class TestCreateConnection:
    @pytest.fixture
    def service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        svc = OpenAPIConnectionService(repository_factory=mock_factory)
        svc._repo = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_validates_base_url_on_create(self, service):
        """SSRF: base_url is validated at creation time."""
        with patch("agentarea_openapi.application.service.validate_url") as mock_validate:
            mock_validate.side_effect = ValueError("private IP")
            with pytest.raises(ValueError, match="private IP"):
                await service.create_connection(
                    name="Test",
                    base_url="http://169.254.169.254/latest",
                )

    @pytest.mark.asyncio
    async def test_validates_spec_url_on_create(self, service):
        """SSRF: spec_url is validated at creation time."""
        with patch("agentarea_openapi.application.service.validate_url") as mock_validate:
            # First call (base_url) succeeds, second (spec_url) fails
            mock_validate.side_effect = [[], ValueError("private IP")]
            with pytest.raises(ValueError, match="private IP"):
                await service.create_connection(
                    name="Test",
                    base_url="https://api.example.com",
                    spec_url="http://169.254.169.254/latest",
                )

    @pytest.mark.asyncio
    async def test_pregenerates_uuid(self, service):
        """Connection ID is pre-generated so secrets are stored atomically."""
        service._repo.create.return_value = OpenAPIConnection(
            name="Test", base_url="https://api.example.com"
        )

        with patch("agentarea_openapi.application.service.validate_url", return_value=[]):
            await service.create_connection(
                name="Test",
                base_url="https://api.example.com",
            )

        # Verify that `id` was passed to repo.create
        call_kwargs = service._repo.create.call_args.kwargs
        assert "id" in call_kwargs
        assert call_kwargs["id"] is not None


class TestUpdateConnection:
    @pytest.fixture
    def service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        svc = OpenAPIConnectionService(repository_factory=mock_factory)
        svc._repo = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_validates_base_url_on_update(self, service):
        """SSRF: base_url is validated on update too."""
        with patch("agentarea_openapi.application.service.validate_url") as mock_validate:
            mock_validate.side_effect = ValueError("private IP")
            with pytest.raises(ValueError, match="private IP"):
                await service.update_connection(
                    connection_id="some-id",
                    base_url="http://169.254.169.254/latest",
                )


class TestSpecParser:
    """Test $ref resolution and path-level parameters."""

    def test_ref_resolution(self):
        from agentarea_openapi.application.spec_parser import parse_openapi_spec

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/items": {
                    "get": {
                        "operationId": "listItems",
                        "parameters": [
                            {"$ref": "#/components/parameters/LimitParam"}
                        ],
                    }
                }
            },
            "components": {
                "parameters": {
                    "LimitParam": {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                        "required": False,
                    }
                }
            },
        }

        tools = parse_openapi_spec(spec)
        assert len(tools) == 1
        assert "limit" in tools[0]["inputSchema"]["properties"]

    def test_path_level_parameters(self):
        from agentarea_openapi.application.spec_parser import parse_openapi_spec

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/items/{item_id}": {
                    "parameters": [
                        {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "get": {
                        "operationId": "getItem",
                        "summary": "Get item",
                    },
                    "delete": {
                        "operationId": "deleteItem",
                        "summary": "Delete item",
                    },
                }
            },
        }

        tools = parse_openapi_spec(spec)
        assert len(tools) == 2
        for tool in tools:
            assert "item_id" in tool["inputSchema"]["properties"]
            assert "item_id" in tool["inputSchema"]["required"]
