"""OpenAPI tool wrapper and factory."""

import json
import logging
import re
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from .base_tool import BaseTool

logger = logging.getLogger(__name__)

_RESULT_MAX_BYTES = 64 * 1024  # 64 KB cap


def _slugify_name(name: str) -> str:
    """Replace characters invalid for function names with underscores."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


class OpenAPITool(BaseTool):
    """Wrapper for an OpenAPI operation that executes real HTTP calls.

    Constructor args:
        operation: Enriched operation record from parse_openapi_operations().
        connection_id: UUID of the OpenAPIConnection row.
        connection_name: Human-readable name for logging.
        openapi_connection_service: OpenAPIConnectionService instance.
    """

    def __init__(
        self,
        operation: dict[str, Any],
        connection_id: UUID,
        connection_name: str,
        openapi_connection_service: Any,
    ):
        self._operation = operation
        self._connection_id = connection_id
        self._connection_name = connection_name
        self._service = openapi_connection_service
        self._name = _slugify_name(operation["name"])
        raw_desc = operation.get("description") or ""
        self._description = raw_desc or f"{operation['method']} {operation['path']}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def get_schema(self) -> dict[str, Any]:
        """Return OpenAI function parameter schema."""
        return {"parameters": self._operation["input_schema"]}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the HTTP call described by the operation.

        Returns structured dict:
            {"success": bool, "result": str|None, "error": str|None,
             "tool_name": str, "status_code": int|None}
        """
        # Fetch connection
        try:
            connection = await self._service.get_connection(self._connection_id)
        except Exception as e:
            logger.error(
                "Failed to fetch OpenAPI connection %s: %s", self._connection_id, e, exc_info=True
            )
            return {
                "success": False,
                "error": f"Failed to fetch connection: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }

        if not connection:
            return {
                "success": False,
                "error": "connection not found",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }

        # Re-validate base_url for SSRF at execution time
        try:
            from agentarea_openapi.application.url_validator import validate_url

            allow_private = getattr(self._service, "_allow_private_urls", False)
            validate_url(connection.base_url, allow_private=allow_private)
        except ValueError as e:
            logger.error(
                "SSRF validation failed for connection %s: %s",
                self._connection_id,
                e,
                exc_info=True,
            )
            return {
                "success": False,
                "error": f"SSRF validation failed: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }

        # Resolve headers (plaintext + secrets); skip auth_config_id for now
        try:
            resolved_headers = await self._service.resolve_headers(connection)
        except Exception as e:
            logger.error(
                "Failed to resolve headers for connection %s: %s",
                self._connection_id,
                e,
                exc_info=True,
            )
            return {
                "success": False,
                "error": f"Failed to resolve headers: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }

        # TODO(#113): resolve auth_config_id via shared MCP auth resolver
        # if connection.auth_config_id is set, static custom_headers are used as-is above.

        # Build URL: substitute path params
        path = self._operation["path"]
        parameters: list[dict[str, Any]] = self._operation.get("parameters", [])

        try:
            for param_meta in parameters:
                if param_meta["in"] == "path":
                    param_name = param_meta["name"]
                    if param_name in kwargs:
                        encoded = quote(str(kwargs[param_name]), safe="")
                        path = path.replace(f"{{{param_name}}}", encoded)
        except Exception as e:
            logger.error("Failed to build path for %s: %s", self.name, e, exc_info=True)
            return {
                "success": False,
                "error": f"Failed to build request path: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }

        base_url = connection.base_url.rstrip("/")
        url = f"{base_url}{path}"

        # Collect query params
        query_params: dict[str, Any] = {}
        for param_meta in parameters:
            if param_meta["in"] == "query":
                param_name = param_meta["name"]
                if param_name in kwargs:
                    query_params[param_name] = kwargs[param_name]

        # Collect header params from kwargs (override connection defaults)
        for param_meta in parameters:
            if param_meta["in"] == "header":
                param_name = param_meta["name"]
                if param_name in kwargs:
                    resolved_headers[param_name] = str(kwargs[param_name])

        # Prepare request body
        json_body: Any = None
        content_body: Any = None
        request_body_meta = self._operation.get("request_body")
        if request_body_meta and "body" in kwargs:
            ct = request_body_meta.get("content_type", "application/json")
            if ct == "application/json":
                json_body = kwargs["body"]
            elif ct.startswith("text/"):
                content_body = str(kwargs["body"])
            else:
                return {
                    "success": False,
                    "error": f"Unsupported request body content type: {ct}",
                    "result": None,
                    "tool_name": self.name,
                    "status_code": None,
                }

        # Execute HTTP call
        method = self._operation["method"]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    params=query_params if query_params else None,
                    headers=resolved_headers if resolved_headers else None,
                    json=json_body,
                    content=content_body,
                )
        except httpx.TimeoutException as e:
            logger.error("HTTP timeout calling %s %s: %s", method, url, e, exc_info=True)
            return {
                "success": False,
                "error": f"HTTP timeout: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }
        except httpx.RequestError as e:
            logger.error("HTTP request error calling %s %s: %s", method, url, e, exc_info=True)
            return {
                "success": False,
                "error": f"HTTP request error: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": None,
            }

        status_code = response.status_code

        # Non-2xx response
        if not (200 <= status_code < 300):
            try:
                body_snippet = response.text[:500]
            except Exception:
                body_snippet = "<unreadable>"
            return {
                "success": False,
                "error": f"HTTP {status_code}: {body_snippet}",
                "result": None,
                "tool_name": self.name,
                "status_code": status_code,
            }

        # Coerce successful response to string
        # 204 No Content or empty body — legitimate empty success, don't fall
        # into the JSON decoder (which would raise and flip to success=False).
        if status_code == 204 or not response.content:
            return {
                "success": True,
                "result": "",
                "error": None,
                "tool_name": self.name,
                "status_code": status_code,
            }

        try:
            ct = response.headers.get("content-type", "")
            if "application/json" in ct:
                result_str = json.dumps(response.json(), ensure_ascii=False)
            elif ct.startswith("text/") or "text" in ct:
                result_str = response.text
            else:
                content_bytes = response.content
                result_str = f"<binary {len(content_bytes)} bytes, content-type={ct}>"
        except Exception as e:
            logger.error("Failed to decode response from %s: %s", url, e, exc_info=True)
            return {
                "success": False,
                "error": f"Failed to decode response: {e}",
                "result": None,
                "tool_name": self.name,
                "status_code": status_code,
            }

        # Apply 64 KB cap
        encoded = result_str.encode("utf-8", errors="replace")
        if len(encoded) > _RESULT_MAX_BYTES:
            original_len = len(encoded)
            truncated = encoded[:_RESULT_MAX_BYTES].decode("utf-8", errors="replace")
            result_str = truncated + f"...[truncated, original {original_len} bytes]"

        return {
            "success": True,
            "result": result_str,
            "error": None,
            "tool_name": self.name,
            "status_code": status_code,
        }


class OpenAPIToolFactory:
    """Factory for creating OpenAPITool instances from a connection."""

    @staticmethod
    async def create_tools_from_connection(
        connection_name_or_id: str | UUID,
        allowed_tools: list[str] | None,
        openapi_connection_service: Any,
    ) -> list[OpenAPITool]:
        """Create OpenAPITool instances for each operation in the connection's spec.

        Args:
            connection_name_or_id: Connection UUID or name string.
            allowed_tools: If non-empty list, only operations with matching names are returned.
            openapi_connection_service: OpenAPIConnectionService instance.

        Returns:
            List of OpenAPITool instances (empty on any error).
        """
        from agentarea_openapi.application.spec_parser import parse_openapi_operations

        # Resolve the connection
        connection = None
        try:
            if isinstance(connection_name_or_id, UUID):
                connection = await openapi_connection_service.get_connection(connection_name_or_id)
            else:
                # Try UUID parse first
                try:
                    uuid_val = UUID(str(connection_name_or_id))
                    connection = await openapi_connection_service.get_connection(uuid_val)
                except (ValueError, AttributeError):
                    pass

                if not connection:
                    # Name-based lookup
                    connections, _ = await openapi_connection_service.list_connections(
                        search=str(connection_name_or_id)
                    )
                    for conn in connections:
                        if conn.name == str(connection_name_or_id):
                            connection = conn
                            break
        except Exception as e:
            logger.error(
                "Failed to resolve OpenAPI connection %r: %s",
                connection_name_or_id,
                e,
                exc_info=True,
            )
            return []

        if not connection:
            logger.warning("OpenAPI connection not found: %r", connection_name_or_id)
            return []

        if not connection.spec_content:
            logger.warning(
                "OpenAPI connection %r has no spec_content; skipping tool creation",
                connection.name,
            )
            return []

        try:
            operations = parse_openapi_operations(connection.spec_content)
        except Exception as e:
            logger.error(
                "Failed to parse OpenAPI spec for connection %r: %s",
                connection.name,
                e,
                exc_info=True,
            )
            return []

        # Filter by allowed_tools if a non-empty list is provided
        if allowed_tools:
            allowed_set = set(allowed_tools)
            operations = [op for op in operations if op["name"] in allowed_set]

        tools = [
            OpenAPITool(op, connection.id, connection.name, openapi_connection_service)
            for op in operations
        ]

        logger.info(
            "Created %d OpenAPI tools from connection %r (allowed_tools=%r)",
            len(tools),
            connection.name,
            allowed_tools,
        )
        return tools
