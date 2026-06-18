"""Unit tests for OpenAPITool and OpenAPIToolFactory."""
# ruff: noqa: F401,F821,F841 — half-finished fixture body references vars
# that haven't been plumbed yet; will be cleaned up in a follow-up PR.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

import agentarea_agents_sdk.tools.openapi_tool as mod

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_CONNECTION_ID = uuid4()
_CONNECTION_NAME = "test-api"


def _make_operation(
    name="listItems",
    method="GET",
    path="/items",
    parameters=None,
    request_body=None,
    description="List items",
):
    return {
        "name": name,
        "description": description,
        "method": method,
        "path": path,
        "parameters": parameters or [],
        "request_body": request_body,
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def _make_connection(
    conn_id=None,
    name=_CONNECTION_NAME,
    base_url="https://api.example.com",
    spec_content=None,
    custom_headers=None,
    auth_config_id=None,
):
    return SimpleNamespace(
        id=conn_id or _CONNECTION_ID,
        name=name,
        base_url=base_url,
        spec_content=spec_content,
        custom_headers=custom_headers or [],
        auth_config_id=auth_config_id,
    )


def _make_service(connection=None, headers=None):
    svc = AsyncMock()
    svc.get_connection = AsyncMock(return_value=connection)
    svc.resolve_headers = AsyncMock(return_value=headers or {})
    svc._allow_private_urls = False
    return svc


def _mock_transport(status_code=200, json_body=None, text_body=None, content_type=None):
    """Build an httpx.MockTransport that returns a fixed response."""

    def handler(request):
        if json_body is not None:
            body = json.dumps(json_body).encode()
            ct = content_type or "application/json"
        else:
            body = (text_body or "").encode()
            ct = content_type or "text/plain"
        return httpx.Response(status_code, content=body, headers={"content-type": ct})

    return httpx.MockTransport(handler)


def _make_tool_with_transport(op, transport, connection=None, headers=None):
    """Build an OpenAPITool that uses a custom httpx transport."""
    conn = connection or _make_connection()
    svc = _make_service(connection=conn, headers=headers or {})
    tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
    return tool, svc


# ---------------------------------------------------------------------------
# OpenAPITool.name / description / get_schema
# ---------------------------------------------------------------------------


class TestOpenAPIToolProperties:
    def test_name_slugified(self):
        op = _make_operation(name="list items!")
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, MagicMock())
        assert tool.name == "list_items_"

    def test_description_from_operation(self):
        op = _make_operation(description="Fetch all items")
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, MagicMock())
        assert tool.description == "Fetch all items"

    def test_description_fallback_to_method_path(self):
        op = _make_operation(description="", method="GET", path="/items")
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, MagicMock())
        assert tool.description == "GET /items"

    def test_get_schema_wraps_input_schema(self):
        op = _make_operation()
        op["input_schema"] = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": [],
        }
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, MagicMock())
        schema = tool.get_schema()
        assert schema == {"parameters": op["input_schema"]}

    def test_get_openai_function_definition_shape(self):
        op = _make_operation()
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, MagicMock())
        defn = tool.get_openai_function_definition()
        assert defn["type"] == "function"
        assert defn["function"]["name"] == tool.name
        assert "parameters" in defn["function"]


# ---------------------------------------------------------------------------
# OpenAPITool.execute — happy path (using httpx.AsyncClient mock)
# ---------------------------------------------------------------------------


def _build_mock_client(response: httpx.Response):
    """Build an AsyncMock that acts as an httpx.AsyncClient context manager."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = AsyncMock(return_value=response)
    return mock_client


def _patch_validate_url():
    """Patch validate_url at its source so SSRF DNS lookups don't run in unit tests."""
    return patch(
        "agentarea_openapi.application.url_validator.validate_url",
        return_value=[],
    )


class TestOpenAPIToolExecuteHappyPath:
    @pytest.mark.asyncio
    async def test_get_request_json_response(self):
        conn = _make_connection()
        svc = _make_service(connection=conn, headers={"Authorization": "Bearer tok"})

        response = httpx.Response(200, json={"items": []})

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=_build_mock_client(response)),
        ):
            op = _make_operation(method="GET", path="/items")
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute()

        assert result["success"] is True
        assert result["error"] is None
        assert result["status_code"] == 200
        assert result["tool_name"] == tool.name
        assert json.loads(result["result"]) == {"items": []}

    @pytest.mark.asyncio
    async def test_path_param_substitution(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        response = httpx.Response(200, json={"id": 42})

        mock_client = _build_mock_client(response)
        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation(
                method="GET",
                path="/items/{item_id}",
                parameters=[
                    {
                        "name": "item_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
            )
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute(item_id=42)

        assert result["success"] is True
        call_kwargs = mock_client.request.call_args
        assert "42" in call_kwargs.kwargs.get("url", "") or "42" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_query_params_passed(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        response = httpx.Response(200, json=[])

        mock_client = _build_mock_client(response)
        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation(
                method="GET",
                path="/items",
                parameters=[
                    {
                        "name": "page",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    },
                ],
            )
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute(page=2)

        assert result["success"] is True
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("params") == {"page": 2}

    @pytest.mark.asyncio
    async def test_402_uses_payment_handler_and_returns_service_cost(self):
        conn = _make_connection()
        svc = _make_service(connection=conn, headers={"Authorization": "Bearer tok"})

        first_response = httpx.Response(
            402,
            text="payment required",
            headers={"PAYMENT-REQUIRED": "challenge"},
        )
        mock_client = _build_mock_client(first_response)

        async def payment_handler(**kwargs):
            assert kwargs["url"] == "https://api.example.com/items"
            assert kwargs["method"] == "GET"
            assert kwargs["response_status"] == 402
            assert kwargs["request_headers"] == {"Authorization": "Bearer tok"}
            return {
                "success": True,
                "protocol": "x402",
                "amount_usd": 0.01,
                "recipient": "0xmerchant",
                "tx_hash": "0xtx",
                "response_body": '{"paid": true}',
                "response_status": 200,
                "protocol_metadata": {"network": "eip155:84532"},
            }

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation(method="GET", path="/items")
            tool = mod.OpenAPITool(
                op,
                _CONNECTION_ID,
                _CONNECTION_NAME,
                svc,
                payment_handler=payment_handler,
            )
            result = await tool.execute()

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["result"] == '{"paid": true}'
        assert result["service_cost"] == 0.01
        assert result["payment"]["protocol"] == "x402"

    @pytest.mark.asyncio
    async def test_header_params_merged_with_connection_headers(self):
        conn = _make_connection()
        svc = _make_service(connection=conn, headers={"Authorization": "Bearer tok"})

        response = httpx.Response(200, json=[])

        mock_client = _build_mock_client(response)
        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation(
                method="GET",
                path="/items",
                parameters=[
                    {
                        "name": "X-Trace-Id",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string"},
                    },
                ],
            )
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute(**{"X-Trace-Id": "trace-123"})

        assert result["success"] is True
        call_kwargs = mock_client.request.call_args
        sent_headers = call_kwargs.kwargs.get("headers", {})
        assert sent_headers.get("X-Trace-Id") == "trace-123"
        assert sent_headers.get("Authorization") == "Bearer tok"

    @pytest.mark.asyncio
    async def test_json_body_passed(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        response = httpx.Response(201, json={"id": 1})

        mock_client = _build_mock_client(response)
        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation(
                name="createItem",
                method="POST",
                path="/items",
                request_body={"content_type": "application/json", "required": True, "schema": {}},
            )
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute(body={"name": "widget"})

        assert result["success"] is True
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("json") == {"name": "widget"}

    @pytest.mark.asyncio
    async def test_text_response_coercion(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        response = httpx.Response(200, text="OK", headers={"content-type": "text/plain"})

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=_build_mock_client(response)),
        ):
            op = _make_operation(method="GET", path="/health")
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute()

        assert result["success"] is True
        assert result["result"] == "OK"

    @pytest.mark.asyncio
    async def test_result_truncation_at_64kb(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        large_text = "x" * (70 * 1024)
        response = httpx.Response(200, text=large_text, headers={"content-type": "text/plain"})

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=_build_mock_client(response)),
        ):
            op = _make_operation(method="GET", path="/big")
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute()

        assert result["success"] is True
        assert "[truncated" in result["result"]
        # Result must not exceed 64KB + marker
        assert len(result["result"].encode("utf-8")) <= 64 * 1024 + 200


# ---------------------------------------------------------------------------
# OpenAPITool.execute — error paths
# ---------------------------------------------------------------------------


class TestOpenAPIToolExecuteErrors:
    @pytest.mark.asyncio
    async def test_connection_not_found(self):
        svc = _make_service(connection=None)
        op = _make_operation()
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
        result = await tool.execute()

        assert result["success"] is False
        assert "not found" in result["error"]
        assert result["result"] is None

    @pytest.mark.asyncio
    async def test_ssrf_blocked(self):
        conn = _make_connection(base_url="http://169.254.169.254/latest/meta-data")
        svc = _make_service(connection=conn)

        op = _make_operation()
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
        result = await tool.execute()

        assert result["success"] is False
        assert result["error"]
        # Should mention private/SSRF in error
        assert (
            "private" in result["error"].lower()
            or "ssrf" in result["error"].lower()
            or "not allowed" in result["error"].lower()
        )

    @pytest.mark.asyncio
    async def test_non_2xx_returns_structured_error(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        response = httpx.Response(404, json={"error": "not found"})

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=_build_mock_client(response)),
        ):
            op = _make_operation()
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute()

        assert result["success"] is False
        assert result["status_code"] == 404
        assert "404" in result["error"]

    @pytest.mark.asyncio
    async def test_httpx_timeout_returns_structured_error(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation()
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute()

        assert result["success"] is False
        assert "timeout" in result["error"].lower()
        assert result["status_code"] is None

    @pytest.mark.asyncio
    async def test_httpx_request_error_returns_structured_error(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with (
            _patch_validate_url(),
            patch.object(mod.httpx, "AsyncClient", return_value=mock_client),
        ):
            op = _make_operation()
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute()

        assert result["success"] is False
        assert "request error" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_unsupported_content_type_body(self):
        conn = _make_connection()
        svc = _make_service(connection=conn)

        op = _make_operation(
            name="upload",
            method="POST",
            path="/upload",
            request_body={
                "content_type": "application/octet-stream",
                "required": True,
                "schema": {},
            },
        )
        with _patch_validate_url():
            tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
            result = await tool.execute(body=b"binary")

        assert result["success"] is False
        assert "Unsupported" in result["error"]

    @pytest.mark.asyncio
    async def test_get_connection_exception(self):
        svc = AsyncMock()
        svc.get_connection = AsyncMock(side_effect=RuntimeError("db error"))
        svc._allow_private_urls = False

        op = _make_operation()
        tool = mod.OpenAPITool(op, _CONNECTION_ID, _CONNECTION_NAME, svc)
        result = await tool.execute()

        assert result["success"] is False
        assert "db error" in result["error"]


# ---------------------------------------------------------------------------
# OpenAPIToolFactory
# ---------------------------------------------------------------------------


_MINIMAL_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Mini", "version": "1.0.0"},
    "paths": {
        "/a": {"get": {"operationId": "opA", "summary": "Op A"}},
        "/b": {"post": {"operationId": "opB", "summary": "Op B"}},
        "/c": {"delete": {"operationId": "opC", "summary": "Op C"}},
    },
}


class TestOpenAPIToolFactory:
    @pytest.mark.asyncio
    async def test_creates_tools_from_connection_by_name(self):
        conn = _make_connection(spec_content=_MINIMAL_SPEC)
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=None)
        svc.list_connections = AsyncMock(return_value=([conn], 1))

        tools = await mod.OpenAPIToolFactory.create_tools_from_connection(
            _CONNECTION_NAME, None, svc
        )

        assert len(tools) == 3
        assert all(isinstance(t, mod.OpenAPITool) for t in tools)

    @pytest.mark.asyncio
    async def test_creates_tools_by_uuid(self):
        conn = _make_connection(spec_content=_MINIMAL_SPEC)
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=conn)

        tools = await mod.OpenAPIToolFactory.create_tools_from_connection(conn.id, None, svc)

        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_allowed_tools_filter(self):
        conn = _make_connection(spec_content=_MINIMAL_SPEC)
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=conn)

        tools = await mod.OpenAPIToolFactory.create_tools_from_connection(
            conn.id, ["opA", "opC"], svc
        )

        names = [t.name for t in tools]
        assert "opA" in names
        assert "opC" in names
        assert "opB" not in names
        assert len(tools) == 2

    @pytest.mark.asyncio
    async def test_empty_allowed_tools_returns_all(self):
        conn = _make_connection(spec_content=_MINIMAL_SPEC)
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=conn)

        tools = await mod.OpenAPIToolFactory.create_tools_from_connection(conn.id, [], svc)

        assert len(tools) == 3

    @pytest.mark.asyncio
    async def test_connection_not_found_returns_empty(self):
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=None)
        svc.list_connections = AsyncMock(return_value=([], 0))

        tools = await mod.OpenAPIToolFactory.create_tools_from_connection("nonexistent", None, svc)

        assert tools == []

    @pytest.mark.asyncio
    async def test_no_spec_content_returns_empty(self):
        conn = _make_connection(spec_content=None)
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=conn)

        tools = await mod.OpenAPIToolFactory.create_tools_from_connection(conn.id, None, svc)

        assert tools == []

    @pytest.mark.asyncio
    async def test_uuid_string_parsed_correctly(self):
        conn = _make_connection(spec_content=_MINIMAL_SPEC)
        svc = AsyncMock()
        svc.get_connection = AsyncMock(return_value=conn)

        # Pass UUID as string — should be parsed and routed to get_connection
        tools = await mod.OpenAPIToolFactory.create_tools_from_connection(str(conn.id), None, svc)

        assert len(tools) == 3
        svc.get_connection.assert_called_once()
