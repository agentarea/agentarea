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
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            if method not in path_item:
                continue

            operation = path_item[method]
            name = operation.get("operationId") or _generate_name(method, path)
            description = operation.get("summary") or operation.get("description") or ""

            input_schema = _build_input_schema(operation)

            tools.append({
                "name": name,
                "description": description,
                "inputSchema": input_schema,
            })

    return tools


def _generate_name(method: str, path: str) -> str:
    """Generate a tool name from HTTP method + path.

    /users/{user_id}/orders -> get_users_user_id_orders
    """
    cleaned = re.sub(r"[{}]", "", path)
    segments = [s for s in cleaned.split("/") if s]
    return f"{method}_{'_'.join(segments)}"


def _build_input_schema(operation: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON Schema from operation parameters and request body."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in operation.get("parameters", []):
        param_name = param.get("name", "")
        if not param_name:
            continue

        param_schema = param.get("schema", {"type": "string"})
        properties[param_name] = param_schema

        if param.get("required", False):
            required.append(param_name)

    request_body = operation.get("requestBody")
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema")
        if body_schema:
            properties["body"] = body_schema
            if request_body.get("required", True):
                required.append("body")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
