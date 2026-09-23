"""Tests for OpenAPIConnectionService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from agentarea_openapi.application import service as service_module
from agentarea_common.testing.flows import MainFlow
from agentarea_openapi.application.service import (
    MissingHeaderSecretError,
    OpenAPIConnectionService,
    fetch_and_parse_spec,
)
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.schemas.dto import (
    OpenAPIConnectionCreate,
    OpenAPIConnectionUpdate,
)

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
        mock_factory = MagicMock()
        mock_factory.create_repository.return_value = AsyncMock()
        return OpenAPIConnectionService(repository_factory=mock_factory, secret_manager=AsyncMock())

    @pytest.mark.flow(MainFlow.OPENAPI_CONNECTIONS)
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


class TestResolveHeaders:
    @pytest.mark.asyncio
    async def test_auth_config_overrides_static_authorization(self):
        mock_factory = MagicMock()
        mock_factory.create_repository.return_value = AsyncMock()
        resolver = AsyncMock(return_value={"Authorization": "OAuth fresh-token"})
        service = OpenAPIConnectionService(
            repository_factory=mock_factory,
            secret_manager=AsyncMock(),
            auth_header_resolver=resolver,
        )
        conn = OpenAPIConnection(
            name="Metrica",
            base_url="https://api-metrika.yandex.net",
            auth_config_id=uuid4(),
            custom_headers=[
                {"name": "Accept", "secret": False, "value": "application/json"},
                {"name": "Authorization", "secret": False, "value": "Bearer stale"},
            ],
            allowed_auth_origins=["https://api-metrika.yandex.net"],
        )

        headers = await service.resolve_headers(conn)

        assert headers == {
            "Accept": "application/json",
            "Authorization": "OAuth fresh-token",
        }
        resolver.assert_awaited_once_with(
            conn.auth_config_id,
            "https://api-metrika.yandex.net",
            ["https://api-metrika.yandex.net"],
        )

    @pytest.mark.asyncio
    async def test_auth_config_is_not_sent_to_another_origin(self):
        mock_factory = MagicMock()
        mock_factory.create_repository.return_value = AsyncMock()
        resolver = AsyncMock(return_value={"Authorization": "OAuth token"})
        service = OpenAPIConnectionService(
            repository_factory=mock_factory,
            secret_manager=AsyncMock(),
            auth_header_resolver=resolver,
        )
        conn = OpenAPIConnection(
            name="Metrica",
            base_url="https://attacker.example",
            auth_config_id=uuid4(),
            allowed_auth_origins=["https://api-metrika.yandex.net"],
        )

        with pytest.raises(MissingHeaderSecretError, match="cannot send OAuth credentials"):
            await service.resolve_headers(conn)
        resolver.assert_not_awaited()


class TestCreateConnection:
    @pytest.fixture
    def service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        svc = OpenAPIConnectionService(repository_factory=mock_factory, secret_manager=AsyncMock())
        svc._repo = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_validates_base_url_on_create(self, service):
        """SSRF: base_url is validated at creation time."""
        with patch("agentarea_openapi.application.service.validate_url") as mock_validate:
            mock_validate.side_effect = ValueError("private IP")
            payload = OpenAPIConnectionCreate.model_construct(
                name="Test",
                base_url="http://169.254.169.254/latest",
            )
            with pytest.raises(ValueError, match="private IP"):
                await service.create_connection(payload)

    @pytest.mark.asyncio
    async def test_validates_spec_url_on_create(self, service):
        """SSRF: spec_url is validated at creation time."""
        with patch("agentarea_openapi.application.service.validate_url") as mock_validate:
            # First call (base_url) succeeds, second (spec_url) fails
            mock_validate.side_effect = [[], ValueError("private IP")]
            payload = OpenAPIConnectionCreate.model_construct(
                name="Test",
                base_url="https://api.example.com",
                spec_url="http://169.254.169.254/latest",
            )
            with pytest.raises(ValueError, match="private IP"):
                await service.create_connection(payload)

    @pytest.mark.asyncio
    async def test_pregenerates_uuid(self, service):
        """Connection ID is pre-generated so secrets are stored atomically."""
        service._repo.create.return_value = OpenAPIConnection(
            name="Test", base_url="https://api.example.com"
        )

        with patch("agentarea_openapi.application.service.validate_url", return_value=[]):
            payload = OpenAPIConnectionCreate.model_construct(
                name="Test",
                base_url="https://api.example.com",
            )
            await service.create_connection(payload)

        # Verify that `id` was passed to repo.create
        call_kwargs = service._repo.create.call_args.kwargs
        assert "id" in call_kwargs
        assert call_kwargs["id"] is not None


class TestUpdateConnection:
    @pytest.fixture
    def service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        svc = OpenAPIConnectionService(repository_factory=mock_factory, secret_manager=AsyncMock())
        svc._repo = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_validates_base_url_on_update(self, service):
        """SSRF: base_url is validated on update too."""
        with patch("agentarea_openapi.application.service.validate_url") as mock_validate:
            mock_validate.side_effect = ValueError("private IP")
            payload = OpenAPIConnectionUpdate.model_construct(
                base_url="http://169.254.169.254/latest",
            )
            # Mark base_url as explicitly set so model_dump(exclude_unset=True) includes it.
            payload.__pydantic_fields_set__.add("base_url")
            with pytest.raises(ValueError, match="private IP"):
                await service.update_connection(
                    connection_id="some-id",
                    payload=payload,
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
                        "parameters": [{"$ref": "#/components/parameters/LimitParam"}],
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
                        {
                            "name": "item_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
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


BARE_DATE_YAML_SPEC = """\
openapi: 3.0.0
info:
  title: Dated API
  version: 2024-01-01
x-released-at: 2024-01-01T10:30:00Z
paths:
  /users:
    get:
      operationId: listUsers
      summary: List users
"""


def _serve(text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, text=text))
    monkeypatch.setattr(
        service_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )


class TestYamlSpecWithBareDates:
    @pytest.mark.parametrize(
        "spec_url",
        ["http://127.0.0.1/openapi.yaml", "http://127.0.0.1/openapi"],
    )
    @pytest.mark.asyncio
    async def test_bare_dates_stay_strings(self, spec_url, monkeypatch):
        _serve(BARE_DATE_YAML_SPEC, monkeypatch)

        spec = await fetch_and_parse_spec(spec_url, allow_private=True)

        assert spec["info"]["version"] == "2024-01-01"
        assert spec["x-released-at"] == "2024-01-01T10:30:00Z"
        assert json.loads(json.dumps(spec)) == spec

    @pytest.mark.asyncio
    async def test_create_connection_stores_json_compatible_spec(self, monkeypatch):
        _serve(BARE_DATE_YAML_SPEC, monkeypatch)
        mock_factory = MagicMock()
        mock_factory.create_repository.return_value = AsyncMock()
        service = OpenAPIConnectionService(
            repository_factory=mock_factory,
            secret_manager=AsyncMock(),
            allow_private_urls=True,
        )

        await service.create_connection(
            OpenAPIConnectionCreate.model_construct(
                name="Dated",
                base_url="https://api.example.com",
                spec_url="http://127.0.0.1/openapi.yaml",
            )
        )

        stored = service._repo.create.call_args.kwargs
        assert stored["spec_content"]["info"]["version"] == "2024-01-01"
        assert json.loads(json.dumps(stored["spec_content"])) == stored["spec_content"]
        assert [t["name"] for t in stored["available_tools"]] == ["listUsers"]
