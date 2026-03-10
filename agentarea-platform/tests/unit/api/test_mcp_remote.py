"""Unit tests for the mcp_remote JSON-RPC proxy router."""

import pytest

from agentarea_api.api.v1.mcp_remote import (
    ALLOWED_METHODS,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    JsonRpcRequest,
    JsonRpcResponse,
    _error_response,
    router,
)


# ---------------------------------------------------------------------------
# Router metadata
# ---------------------------------------------------------------------------


class TestRouterMetadata:
    def test_router_prefix(self):
        assert router.prefix == "/mcp/remote"

    def test_router_tags(self):
        assert "mcp-remote" in router.tags

    def test_rpc_route_exists(self):
        paths = [r.path for r in router.routes]
        assert "/mcp/remote/{instance_name}/rpc" in paths


# ---------------------------------------------------------------------------
# Method whitelist
# ---------------------------------------------------------------------------


class TestMethodWhitelist:
    def test_tools_list_allowed(self):
        assert "tools/list" in ALLOWED_METHODS

    def test_tools_call_allowed(self):
        assert "tools/call" in ALLOWED_METHODS

    def test_resources_list_allowed(self):
        assert "resources/list" in ALLOWED_METHODS

    def test_resources_read_allowed(self):
        assert "resources/read" in ALLOWED_METHODS

    def test_prompts_list_allowed(self):
        assert "prompts/list" in ALLOWED_METHODS

    def test_prompts_get_allowed(self):
        assert "prompts/get" in ALLOWED_METHODS

    def test_random_method_not_allowed(self):
        assert "admin/shutdown" not in ALLOWED_METHODS

    def test_whitelist_is_frozen(self):
        with pytest.raises(AttributeError):
            ALLOWED_METHODS.add("bad/method")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class TestJsonRpcRequest:
    def test_defaults(self):
        req = JsonRpcRequest(method="tools/list")
        assert req.jsonrpc == "2.0"
        assert req.params is None
        assert req.id is None

    def test_full_request(self):
        req = JsonRpcRequest(
            jsonrpc="2.0",
            method="tools/call",
            params={"name": "echo", "arguments": {"msg": "hi"}},
            id=42,
        )
        assert req.method == "tools/call"
        assert req.id == 42
        assert req.params["name"] == "echo"

    def test_string_id(self):
        req = JsonRpcRequest(method="tools/list", id="req-abc")
        assert req.id == "req-abc"


class TestJsonRpcResponse:
    def test_success_response(self):
        resp = JsonRpcResponse(id=1, result={"tools": []})
        assert resp.jsonrpc == "2.0"
        assert resp.result == {"tools": []}
        assert resp.error is None

    def test_error_response(self):
        resp = _error_response(1, METHOD_NOT_FOUND, "not found")
        assert resp.id == 1
        assert resp.result is None
        assert resp.error is not None
        assert resp.error.code == METHOD_NOT_FOUND
        assert resp.error.message == "not found"

    def test_error_with_data(self):
        resp = _error_response(None, INTERNAL_ERROR, "boom", data={"detail": "x"})
        assert resp.id is None
        assert resp.error.data == {"detail": "x"}


# ---------------------------------------------------------------------------
# Error response helpers
# ---------------------------------------------------------------------------


class TestErrorResponse:
    def test_parse_error_code(self):
        from agentarea_api.api.v1.mcp_remote import PARSE_ERROR

        assert PARSE_ERROR == -32700

    def test_invalid_request_code(self):
        assert INVALID_REQUEST == -32600

    def test_method_not_found_code(self):
        assert METHOD_NOT_FOUND == -32601

    def test_internal_error_code(self):
        assert INTERNAL_ERROR == -32603

    def test_error_response_preserves_id(self):
        resp = _error_response("req-1", METHOD_NOT_FOUND, "nope")
        assert resp.id == "req-1"

    def test_error_response_null_id(self):
        resp = _error_response(None, INVALID_REQUEST, "bad")
        assert resp.id is None
