"""Tests for OpenAPI spec parser."""

import pytest

from agentarea_openapi.application.spec_parser import parse_openapi_spec


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List all users",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                ],
            },
            "post": {
                "operationId": "createUser",
                "summary": "Create a user",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string"},
                                },
                                "required": ["name", "email"],
                            }
                        }
                    }
                },
            },
        },
        "/users/{user_id}": {
            "get": {
                "operationId": "getUser",
                "summary": "Get a user by ID",
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
        },
    },
}


class TestParseOpenAPISpec:
    def test_extracts_all_operations(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        names = [t["name"] for t in tools]
        assert "listUsers" in names
        assert "createUser" in names
        assert "getUser" in names
        assert len(tools) == 3

    def test_uses_operation_id(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "listUsers")
        assert tool["description"] == "List all users"

    def test_query_params_in_input_schema(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "listUsers")
        props = tool["inputSchema"]["properties"]
        assert "page" in props
        assert "limit" in props
        assert props["page"]["type"] == "integer"

    def test_path_params_are_required(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "getUser")
        assert "user_id" in tool["inputSchema"]["properties"]
        assert "user_id" in tool["inputSchema"]["required"]

    def test_request_body_as_body_property(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "createUser")
        assert "body" in tool["inputSchema"]["properties"]
        body_schema = tool["inputSchema"]["properties"]["body"]
        assert "name" in body_schema["properties"]
        assert "email" in body_schema["properties"]

    def test_fallback_name_without_operation_id(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/orders/{order_id}/items": {
                    "get": {
                        "summary": "List order items",
                        "parameters": [
                            {"name": "order_id", "in": "path", "required": True, "schema": {"type": "string"}}
                        ],
                    }
                }
            },
        }
        tools = parse_openapi_spec(spec)
        assert len(tools) == 1
        assert tools[0]["name"] == "get_orders_order_id_items"

    def test_empty_paths(self):
        spec = {"openapi": "3.0.0", "info": {"title": "Empty", "version": "1.0.0"}, "paths": {}}
        tools = parse_openapi_spec(spec)
        assert tools == []

    def test_rejects_swagger_2(self):
        spec = {"swagger": "2.0", "info": {"title": "Old", "version": "1.0.0"}, "paths": {}}
        with pytest.raises(ValueError, match="OpenAPI 3.x"):
            parse_openapi_spec(spec)

    def test_operation_with_no_params_or_body(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {"/health": {"get": {"operationId": "healthCheck", "summary": "Health check"}}},
        }
        tools = parse_openapi_spec(spec)
        assert len(tools) == 1
        assert tools[0]["inputSchema"]["properties"] == {}
