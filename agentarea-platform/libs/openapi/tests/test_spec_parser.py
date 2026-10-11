"""Tests for OpenAPI spec parser."""

import pytest

from agentarea_openapi.application.spec_parser import (
    openapi_spec_info,
    parse_openapi_operations,
    parse_openapi_spec,
)


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


SAMPLE_SPEC_WITH_REFS = {
    "openapi": "3.0.0",
    "info": {"title": "Ref Test API", "version": "1.0.0"},
    "components": {
        "schemas": {
            "UserBody": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                "required": ["name", "email"],
            }
        },
        "parameters": {
            "UserIdParam": {
                "name": "user_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        },
    },
    "paths": {
        "/users/{user_id}": {
            "parameters": [{"$ref": "#/components/parameters/UserIdParam"}],
            "put": {
                "operationId": "updateUser",
                "summary": "Update user",
                "parameters": [
                    {"name": "dry_run", "in": "query", "required": False, "schema": {"type": "boolean"}},
                    {"name": "X-Trace-Id", "in": "header", "required": False, "schema": {"type": "string"}},
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserBody"}
                        }
                    },
                },
            },
        }
    },
}


class TestParseOpenAPIOperations:
    def test_returns_method_and_path(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        get_users = next(op for op in ops if op["name"] == "listUsers")
        assert get_users["method"] == "GET"
        assert get_users["path"] == "/users"

    def test_returns_all_operations(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        names = [op["name"] for op in ops]
        assert "listUsers" in names
        assert "createUser" in names
        assert "getUser" in names
        assert len(ops) == 3

    def test_query_param_in_location(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        list_users = next(op for op in ops if op["name"] == "listUsers")
        param_ins = {p["name"]: p["in"] for p in list_users["parameters"]}
        assert param_ins["page"] == "query"
        assert param_ins["limit"] == "query"

    def test_path_param_in_location(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        get_user = next(op for op in ops if op["name"] == "getUser")
        param_ins = {p["name"]: p["in"] for p in get_user["parameters"]}
        assert param_ins["user_id"] == "path"

    def test_path_param_required_flag(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        get_user = next(op for op in ops if op["name"] == "getUser")
        user_id_param = next(p for p in get_user["parameters"] if p["name"] == "user_id")
        assert user_id_param["required"] is True

    def test_request_body_present(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        create_user = next(op for op in ops if op["name"] == "createUser")
        assert create_user["request_body"] is not None
        assert create_user["request_body"]["content_type"] == "application/json"
        assert create_user["request_body"]["required"] is True

    def test_request_body_none_when_absent(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        list_users = next(op for op in ops if op["name"] == "listUsers")
        assert list_users["request_body"] is None

    def test_input_schema_present(self):
        ops = parse_openapi_operations(SAMPLE_SPEC)
        list_users = next(op for op in ops if op["name"] == "listUsers")
        assert "type" in list_users["input_schema"]
        assert list_users["input_schema"]["type"] == "object"
        assert "page" in list_users["input_schema"]["properties"]

    def test_ref_in_path_level_parameter(self):
        ops = parse_openapi_operations(SAMPLE_SPEC_WITH_REFS)
        update_user = next(op for op in ops if op["name"] == "updateUser")
        param_names = {p["name"] for p in update_user["parameters"]}
        assert "user_id" in param_names

    def test_ref_in_request_body_schema(self):
        ops = parse_openapi_operations(SAMPLE_SPEC_WITH_REFS)
        update_user = next(op for op in ops if op["name"] == "updateUser")
        rb = update_user["request_body"]
        assert rb is not None
        assert "name" in rb["schema"].get("properties", {})

    def test_header_param_in_location(self):
        ops = parse_openapi_operations(SAMPLE_SPEC_WITH_REFS)
        update_user = next(op for op in ops if op["name"] == "updateUser")
        param_ins = {p["name"]: p["in"] for p in update_user["parameters"]}
        assert param_ins["X-Trace-Id"] == "header"

    def test_path_level_and_operation_level_params_merged(self):
        ops = parse_openapi_operations(SAMPLE_SPEC_WITH_REFS)
        update_user = next(op for op in ops if op["name"] == "updateUser")
        param_names = {p["name"] for p in update_user["parameters"]}
        # path-level: user_id; operation-level: dry_run, X-Trace-Id
        assert "user_id" in param_names
        assert "dry_run" in param_names
        assert "X-Trace-Id" in param_names

    def test_cycle_breaking(self):
        cyclic_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Cyclic", "version": "1.0.0"},
            "components": {
                "schemas": {
                    "Cyclic": {"$ref": "#/components/schemas/Cyclic"},
                }
            },
            "paths": {
                "/test": {
                    "get": {
                        "operationId": "testOp",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Cyclic"}
                                }
                            }
                        },
                    }
                }
            },
        }
        # Must not raise; cycle is broken and returns empty schema
        ops = parse_openapi_operations(cyclic_spec)
        assert len(ops) == 1

    def test_rejects_swagger_2(self):
        spec = {"swagger": "2.0", "info": {"title": "Old", "version": "1.0.0"}, "paths": {}}
        with pytest.raises(ValueError, match="OpenAPI 3.x"):
            parse_openapi_operations(spec)

    def test_parse_openapi_spec_returns_ui_contract_shape(self):
        """parse_openapi_spec must return {name, description, inputSchema} for UI contract."""
        tools = parse_openapi_spec(SAMPLE_SPEC)
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
            # Must NOT have enriched fields in the UI-contract output
            assert "method" not in t
            assert "path" not in t


@pytest.mark.parametrize("operation_id", ["wait", "completion", "load_tools"])
def test_an_operation_named_like_a_workflow_builtin_is_refused(operation_id):
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Jobs", "version": "1.0.0"},
        "paths": {"/jobs": {"get": {"operationId": operation_id}}},
    }

    with pytest.raises(ValueError, match=f"'{operation_id}'.*reserved"):
        parse_openapi_spec(spec)


COLLECT_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Metrica", "version": "1.0.0"},
    "paths": {
        "/collect/{ms}": {
            "get": {
                "operationId": "collect",
                "parameters": [
                    {"name": "ms", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "ms", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "dl", "in": "query", "required": True, "schema": {"type": "string"}},
                ],
            }
        },
        "/hits": {
            "get": {
                "operationId": "hits",
                "parameters": [
                    {"name": "ms", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "dl", "in": "query", "required": True, "schema": {"type": "string"}},
                ],
            }
        },
    },
}


class TestConfiguredQueryParams:
    """A query parameter the connection supplies itself is not the agent's to fill."""

    def test_a_configured_query_param_leaves_the_input_schema(self):
        [_, hits] = parse_openapi_spec(COLLECT_SPEC, configured_query_params={"ms"})

        assert set(hits["inputSchema"]["properties"]) == {"dl"}
        assert hits["inputSchema"]["required"] == ["dl"]

    def test_a_configured_query_param_leaves_the_operation(self):
        [_, hits] = parse_openapi_operations(COLLECT_SPEC, configured_query_params={"ms"})

        assert [p["name"] for p in hits["parameters"]] == ["dl"]
        assert set(hits["input_schema"]["properties"]) == {"dl"}

    def test_a_path_param_of_the_same_name_stays(self):
        [collect, _] = parse_openapi_operations(COLLECT_SPEC, configured_query_params={"ms"})

        assert [(p["name"], p["in"]) for p in collect["parameters"]] == [
            ("ms", "path"),
            ("dl", "query"),
        ]
        assert set(collect["input_schema"]["properties"]) == {"ms", "dl"}

    def test_without_configured_params_the_schema_is_the_spec(self):
        [_, hits] = parse_openapi_spec(COLLECT_SPEC)

        assert set(hits["inputSchema"]["properties"]) == {"ms", "dl"}


_MALFORMED_SPECS = {
    "operation is a string": {"openapi": "3.0.0", "paths": {"/a": {"get": "x"}}},
    "operation parameters is a string": {
        "openapi": "3.0.0",
        "paths": {"/a": {"get": {"parameters": "x"}}},
    },
    "a parameter is a string": {
        "openapi": "3.0.0",
        "paths": {"/a": {"get": {"parameters": ["x"]}}},
    },
    "path parameters is an object": {
        "openapi": "3.0.0",
        "paths": {"/a": {"parameters": {"name": "x"}, "get": {}}},
    },
    "a parameter name is not text": {
        "openapi": "3.0.0",
        "paths": {"/a": {"get": {"parameters": [{"name": ["x"], "in": "query"}]}}},
    },
    "a parameter schema is a string": {
        "openapi": "3.0.0",
        "paths": {"/a": {"get": {"parameters": [{"name": "q", "schema": "string"}]}}},
    },
    "operationId is not text": {
        "openapi": "3.0.0",
        "paths": {"/a": {"get": {"operationId": 7}}},
    },
    "summary is not text": {
        "openapi": "3.0.0",
        "paths": {"/a": {"get": {"summary": {"x": 1}}}},
    },
    "requestBody is a string": {
        "openapi": "3.0.0",
        "paths": {"/a": {"post": {"requestBody": "x"}}},
    },
    "requestBody content is a list": {
        "openapi": "3.0.0",
        "paths": {"/a": {"post": {"requestBody": {"content": ["application/json"]}}}},
    },
    "a media type is a string": {
        "openapi": "3.0.0",
        "paths": {"/a": {"post": {"requestBody": {"content": {"application/json": "x"}}}}},
    },
    "a body schema is a list": {
        "openapi": "3.0.0",
        "paths": {
            "/a": {"post": {"requestBody": {"content": {"text/plain": {"schema": ["x"]}}}}}
        },
    },
    "paths is a list": {"openapi": "3.0.0", "paths": ["/a"]},
    "openapi is a number": {"openapi": 3.0, "paths": {}},
    "the spec is a list": ["openapi", "3.0.0"],
    "info is a string": {"openapi": "3.0.0", "info": "str", "paths": {}},
    "servers is a string": {"openapi": "3.0.0", "servers": "notalist", "paths": {}},
    "a server is a string": {"openapi": "3.0.0", "servers": ["x"], "paths": {}},
    "a server url is not text": {"openapi": "3.0.0", "servers": [{"url": 1}], "paths": {}},
}


@pytest.mark.parametrize("spec", _MALFORMED_SPECS.values(), ids=_MALFORMED_SPECS.keys())
def test_a_malformed_spec_is_a_value_error(spec):
    """Every malformed spec is the ValueError the routes answer 400 with.

    These raised AttributeError/TypeError (``.get`` on a string), which the
    preview and create routes do not map, so a member's bad document was a 500.
    """
    with pytest.raises(ValueError, match="OpenAPI"):
        parse_openapi_spec(spec)  # type: ignore[arg-type]


def test_spec_info_reads_title_version_and_first_server():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "T", "description": "D", "version": 1.0},
        "servers": [{"url": "https://api.example.com"}, {"url": "https://b.example.com"}],
        "paths": {},
    }

    assert openapi_spec_info(spec) == {
        "title": "T",
        "description": "D",
        "version": "1.0",
        "base_url": "https://api.example.com",
    }


def test_spec_info_of_a_spec_without_info_or_servers():
    assert openapi_spec_info({"openapi": "3.0.0"}) == {
        "title": None,
        "description": None,
        "version": None,
        "base_url": None,
    }
