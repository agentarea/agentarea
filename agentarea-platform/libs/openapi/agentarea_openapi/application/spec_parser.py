"""Parse OpenAPI 3.x specs into tool definitions."""

import re
from collections.abc import Collection
from typing import Any

from agentarea_governance.domain.tool_calls import CONTROL_FLOW_TOOL_NAMES


def parse_openapi_operations(
    spec: dict[str, Any], configured_query_params: Collection[str] = ()
) -> list[dict[str, Any]]:
    """Extract enriched per-operation records from an OpenAPI 3.x spec.

    Each operation record includes HTTP method, path, parameters with `in`
    location, request body metadata, and the flat input_schema for LLM use.
    Query parameters named in ``configured_query_params`` are left out: the
    connection sends its own value for them, so they are not the agent's to fill.

    Raises ValueError for non-OpenAPI 3.x specs (same rules as parse_openapi_spec)
    and for a spec whose objects are not the types OpenAPI says they are: the
    spec is a member's document, and a malformed one is their 400, not our 500.
    """
    if not isinstance(spec, dict):
        raise ValueError("An OpenAPI spec must be an object")
    if "swagger" in spec:
        raise ValueError("Swagger 2.0 specs are not supported. Please convert to OpenAPI 3.x.")

    openapi_version = spec.get("openapi", "")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3."):
        raise ValueError(f"Only OpenAPI 3.x specs are supported, got: {openapi_version!r}")

    paths = _expect_object(spec.get("paths") or {}, "paths")
    operations: list[dict[str, Any]] = []

    for path, path_item in paths.items():
        if not isinstance(path, str):
            raise ValueError(f"Invalid OpenAPI spec: path {path!r} must be a string")
        if not path_item or not isinstance(path_item, dict):
            continue
        where = f"paths[{path!r}]"

        # Path-level parameters shared across all operations on this path
        path_params = _parameters(path_item, spec, where)

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            if method not in path_item:
                continue

            op_where = f"{where}.{method}"
            operation = _expect_object(path_item[method], op_where)
            operation_id = _optional_str(operation.get("operationId"), f"{op_where}.operationId")
            summary = _optional_str(operation.get("summary"), f"{op_where}.summary")
            details = _optional_str(operation.get("description"), f"{op_where}.description")
            name = operation_id or _generate_name(method, path)
            description = summary or details or ""

            # Resolve and merge parameters, preserving `in` location
            op_params = _parameters(operation, spec, op_where)
            merged_params = [
                p
                for p in _merge_parameters(path_params, op_params)
                if not _is_configured(p, configured_query_params)
            ]

            # Build enriched parameter list with `in` location
            parameters: list[dict[str, Any]] = []
            for param in merged_params:
                param_name = param.get("name", "")
                if not param_name:
                    continue
                param_schema = _param_schema(param, spec, f"{op_where} parameter {param_name!r}")
                parameters.append(
                    {
                        "name": param_name,
                        "in": param.get("in", "query"),
                        "required": param.get("required", False),
                        "schema": param_schema,
                    }
                )

            # Resolve request body metadata
            request_body: dict[str, Any] | None = None
            body = _request_body(operation, spec, op_where)
            if body is not None:
                raw_body, content = body
                # Pick first content type; prefer application/json
                content_type = "application/json"
                body_schema: dict[str, Any] | None = None
                if "application/json" in content:
                    body_schema = _media_schema(content, "application/json", spec, op_where)
                elif content:
                    content_type = next(iter(content))
                    body_schema = _media_schema(content, content_type, spec, op_where)
                request_body = {
                    "content_type": content_type,
                    "required": raw_body.get("required", True),
                    "schema": body_schema or {},
                }

            input_schema = _build_input_schema(
                operation, path_params, spec, configured_query_params, op_where
            )

            operations.append(
                {
                    "name": name,
                    "description": description,
                    "method": method.upper(),
                    "path": path,
                    "parameters": parameters,
                    "request_body": request_body,
                    "input_schema": input_schema,
                }
            )

    return operations


def parse_openapi_spec(
    spec: dict[str, Any], configured_query_params: Collection[str] = ()
) -> list[dict[str, Any]]:
    """Extract operations from an OpenAPI 3.x spec as tool definitions.

    Thin projector over parse_openapi_operations — returns the
    {name, description, inputSchema} shape for the UI contract (available_tools column).

    Raises ValueError for non-OpenAPI 3.x specs, for a malformed spec (its
    ``info`` and ``servers`` included), and for an operation whose tool name a
    workflow built-in owns: the built-in would shadow it and skip policy.
    """
    operations = parse_openapi_operations(spec, configured_query_params)
    openapi_spec_info(spec)
    for op in operations:
        if re.sub(r"[^a-zA-Z0-9_-]", "_", op["name"]) in CONTROL_FLOW_TOOL_NAMES:
            raise ValueError(
                f"Operation {op['name']!r} ({op['method']} {op['path']}) uses a tool name "
                "reserved for a workflow built-in; give it a different operationId"
            )
    return [
        {
            "name": op["name"],
            "description": op["description"],
            "inputSchema": op["input_schema"],
        }
        for op in operations
    ]


def openapi_spec_info(spec: dict[str, Any]) -> dict[str, str | None]:
    """The spec's title, description, version and first server url, type-checked.

    Raises ValueError when ``info`` is not an object, ``servers`` is not a list
    of server objects, or one of their fields is not text.
    """
    info = _expect_object(spec.get("info") or {}, "info")
    servers = spec.get("servers") or []
    if not isinstance(servers, list):
        raise ValueError("Invalid OpenAPI spec: servers must be a list")
    urls = [
        _optional_str(
            _expect_object(server, f"servers[{index}]").get("url"), f"servers[{index}].url"
        )
        for index, server in enumerate(servers)
    ]
    return {
        "title": _text(info.get("title"), "info.title"),
        "description": _text(info.get("description"), "info.description"),
        "version": _text(info.get("version"), "info.version"),
        "base_url": urls[0] if urls else None,
    }


def _text(value: Any, where: str) -> str | None:
    """A text field; a YAML number (``version: 1.0``) reads as its text."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return _optional_str(value, where)


def _expect_object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Invalid OpenAPI spec: {where} must be an object")
    return value


def _optional_str(value: Any, where: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"Invalid OpenAPI spec: {where} must be a string")
    return value


def _schema(value: Any, where: str) -> Any:
    """A schema object; OpenAPI 3.1 (JSON Schema 2020-12) also allows a boolean."""
    if not isinstance(value, dict | bool):
        raise ValueError(f"Invalid OpenAPI spec: {where} must be a schema object")
    return value


def _parameters(
    container: dict[str, Any], spec: dict[str, Any], where: str
) -> list[dict[str, Any]]:
    """The ``parameters`` of a path item or operation, refs resolved and type-checked."""
    raw = container.get("parameters") or []
    if not isinstance(raw, list):
        raise ValueError(f"Invalid OpenAPI spec: {where}.parameters must be a list")
    params: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        param = _expect_object(_resolve_ref(item, spec), f"{where}.parameters[{index}]")
        _optional_str(param.get("name"), f"{where}.parameters[{index}].name")
        _optional_str(param.get("in"), f"{where}.parameters[{index}].in")
        params.append(param)
    return params


def _param_schema(param: dict[str, Any], spec: dict[str, Any], where: str) -> Any:
    return _schema(_resolve_ref(param.get("schema", {"type": "string"}), spec), f"{where} schema")


def _request_body(
    operation: dict[str, Any], spec: dict[str, Any], where: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """The operation's request body and its ``content`` map, or None without one."""
    raw_body = operation.get("requestBody")
    if not raw_body:
        return None
    body = _expect_object(_resolve_ref(raw_body, spec), f"{where}.requestBody")
    content = _expect_object(body.get("content") or {}, f"{where}.requestBody.content")
    return body, content


def _media_schema(
    content: dict[str, Any], content_type: str, spec: dict[str, Any], where: str
) -> Any:
    media_where = f"{where}.requestBody.content[{content_type!r}]"
    media = _expect_object(content[content_type], media_where)
    return _schema(_resolve_ref(media.get("schema", {}), spec), f"{media_where}.schema")


def _generate_name(method: str, path: str) -> str:
    """Generate a tool name from HTTP method + path.

    /users/{user_id}/orders -> get_users_user_id_orders
    """
    cleaned = re.sub(r"[{}]", "", path)
    segments = [s for s in cleaned.split("/") if s]
    return f"{method}_{'_'.join(segments)}"


def _resolve_ref(
    obj: dict[str, Any], spec: dict[str, Any], _seen: set[str] | None = None
) -> dict[str, Any]:
    """Resolve a $ref pointer within the spec. Returns the resolved object.

    Handles cycle detection to avoid infinite recursion.
    """
    if not isinstance(obj, dict) or "$ref" not in obj:
        return obj

    ref = obj["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        return obj

    if _seen is None:
        _seen = set()
    if ref in _seen:
        return {}  # Break cycles
    _seen.add(ref)

    parts = ref.lstrip("#/").split("/")
    resolved: Any = spec
    for part in parts:
        # Handle JSON Pointer escaping
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(resolved, dict):
            resolved = resolved.get(part)
        else:
            return obj  # Can't resolve further
        if resolved is None:
            return obj

    if isinstance(resolved, dict) and "$ref" in resolved:
        return _resolve_ref(resolved, spec, _seen)

    return resolved


def _merge_parameters(
    path_params: list[dict[str, Any]],
    op_params: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge path-level and operation-level parameters.

    Operation parameters override path-level parameters with the same name+in.
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for p in path_params:
        key = (p.get("name", ""), p.get("in", ""))
        by_key[key] = p
    for p in op_params:
        key = (p.get("name", ""), p.get("in", ""))
        by_key[key] = p  # Operation overrides path
    return list(by_key.values())


def _is_configured(param: dict[str, Any], configured_query_params: Collection[str]) -> bool:
    return param.get("in", "query") == "query" and param.get("name") in configured_query_params


def _build_input_schema(
    operation: dict[str, Any],
    path_params: list[dict[str, Any]],
    spec: dict[str, Any],
    configured_query_params: Collection[str] = (),
    where: str = "operation",
) -> dict[str, Any]:
    """Build a JSON Schema from operation parameters and request body."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    # Resolve and merge parameters
    op_params = _parameters(operation, spec, where)
    merged = _merge_parameters(path_params, op_params)

    for param in merged:
        if _is_configured(param, configured_query_params):
            continue
        param_name = param.get("name", "")
        if not param_name:
            continue

        param_schema = _param_schema(param, spec, f"{where} parameter {param_name!r}")
        properties[param_name] = param_schema

        if param.get("required", False):
            required.append(param_name)

    body = _request_body(operation, spec, where)
    if body is not None:
        request_body, content = body
        if "application/json" in content:
            body_schema = _media_schema(content, "application/json", spec, where)
            if body_schema:
                properties["body"] = body_schema
                if request_body.get("required", True):
                    required.append("body")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
