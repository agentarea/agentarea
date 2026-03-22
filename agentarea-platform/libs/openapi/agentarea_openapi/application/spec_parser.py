"""Parse OpenAPI 3.x specs into tool definitions."""

import re
from typing import Any


def parse_openapi_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract operations from an OpenAPI 3.x spec as tool definitions.

    Each operation becomes a tool with:
    - name: operationId or generated from method + path
    - description: summary or description
    - inputSchema: merged path params, query params, and request body

    Raises ValueError for non-OpenAPI 3.x specs.
    """
    if "swagger" in spec:
        raise ValueError("Swagger 2.0 specs are not supported. Please convert to OpenAPI 3.x.")

    openapi_version = spec.get("openapi", "")
    if not openapi_version.startswith("3."):
        raise ValueError(f"Only OpenAPI 3.x specs are supported, got: {openapi_version!r}")

    paths = spec.get("paths", {})
    tools: list[dict[str, Any]] = []

    for path, path_item in paths.items():
        if not path_item or not isinstance(path_item, dict):
            continue

        # Path-level parameters shared across all operations on this path
        path_params = [_resolve_ref(p, spec) for p in path_item.get("parameters", [])]

        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            if method not in path_item:
                continue

            operation = path_item[method]
            name = operation.get("operationId") or _generate_name(method, path)
            description = operation.get("summary") or operation.get("description") or ""

            input_schema = _build_input_schema(operation, path_params, spec)

            tools.append(
                {
                    "name": name,
                    "description": description,
                    "inputSchema": input_schema,
                }
            )

    return tools


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


def _build_input_schema(
    operation: dict[str, Any],
    path_params: list[dict[str, Any]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Build a JSON Schema from operation parameters and request body."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    # Resolve and merge parameters
    op_params = [_resolve_ref(p, spec) for p in operation.get("parameters", [])]
    merged = _merge_parameters(path_params, op_params)

    for param in merged:
        param_name = param.get("name", "")
        if not param_name:
            continue

        param_schema = _resolve_ref(param.get("schema", {"type": "string"}), spec)
        properties[param_name] = param_schema

        if param.get("required", False):
            required.append(param_name)

    request_body = operation.get("requestBody")
    if request_body:
        request_body = _resolve_ref(request_body, spec)
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema")
        if body_schema:
            body_schema = _resolve_ref(body_schema, spec)
            properties["body"] = body_schema
            if request_body.get("required", True):
                required.append("body")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
