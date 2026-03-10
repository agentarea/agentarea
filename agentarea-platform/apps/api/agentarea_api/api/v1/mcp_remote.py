"""Remote MCP JSON-RPC proxy endpoint.

Exposes workspace MCP server instances externally via a JSON-RPC interface,
allowing external systems to call tools/list, tools/call, etc. on running
MCP instances without direct network access to the container mesh.
"""

import logging
from datetime import timedelta
from typing import Any

from agentarea_api.api.deps.services import get_mcp_server_instance_service
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.config import get_settings
from agentarea_mcp.application.service import MCPServerInstanceService
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/remote", tags=["mcp-remote"])

# Whitelisted JSON-RPC methods that may be proxied to MCP instances.
ALLOWED_METHODS = frozenset(
    {
        "tools/list",
        "tools/call",
        "resources/list",
        "resources/read",
        "prompts/list",
        "prompts/get",
    }
)


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = Field("2.0", description="JSON-RPC version (must be '2.0')")
    method: str = Field(..., description="RPC method name")
    params: dict[str, Any] | None = Field(None, description="Method parameters")
    id: int | str | None = Field(None, description="Request identifier")


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: JsonRpcError | None = None


def _error_response(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> JsonRpcResponse:
    return JsonRpcResponse(
        id=request_id,
        error=JsonRpcError(code=code, message=message, data=data),
    )


# Standard JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


@router.post("/{instance_name}/rpc", response_model=JsonRpcResponse)
async def mcp_remote_rpc(
    instance_name: str,
    body: JsonRpcRequest,
    user_context: UserContextDep,
    service: MCPServerInstanceService = Depends(get_mcp_server_instance_service),
) -> JsonRpcResponse:
    """JSON-RPC proxy to a running MCP server instance.

    Validates the request, resolves the instance by name, and forwards
    the whitelisted method to the MCP server via the MCP Python SDK.
    """
    request_id = body.id

    # ---- validate JSON-RPC version ----
    if body.jsonrpc != "2.0":
        return _error_response(request_id, INVALID_REQUEST, "Only JSON-RPC 2.0 is supported")

    # ---- validate method whitelist ----
    if body.method not in ALLOWED_METHODS:
        return _error_response(
            request_id,
            METHOD_NOT_FOUND,
            f"Method '{body.method}' is not supported. "
            f"Allowed: {', '.join(sorted(ALLOWED_METHODS))}",
        )

    # ---- resolve instance by name ----
    instances = await service.list()
    instance = next((i for i in instances if i.name == instance_name), None)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"MCP instance '{instance_name}' not found")

    if instance.status != "running":
        return _error_response(
            request_id,
            INTERNAL_ERROR,
            f"MCP instance '{instance_name}' is not running (status: {instance.status})",
        )

    # ---- determine MCP URL ----
    instance_type = (instance.json_spec or {}).get("type", "docker")
    if instance_type == "url":
        mcp_url = (instance.json_spec or {}).get("url", "")
        if not mcp_url:
            return _error_response(
                request_id, INTERNAL_ERROR, "URL-type instance has no url configured"
            )
    else:
        gateway_url = get_settings().mcp.MCP_GATEWAY_URL
        mcp_url = f"{gateway_url}/mcp/{instance.id}/mcp"

    # ---- optional auth headers ----
    headers: dict[str, str] = {}
    auth_header = (instance.json_spec or {}).get("auth_header")
    auth_value = (instance.json_spec or {}).get("auth_value")
    if auth_header and auth_value:
        headers[auth_header] = auth_value

    # ---- proxy to MCP server ----
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with streamablehttp_client(
            mcp_url, timeout=timedelta(seconds=30), headers=headers
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await _dispatch_method(session, body.method, body.params or {})

        return JsonRpcResponse(id=request_id, result=result)

    except Exception as exc:
        logger.exception("MCP RPC proxy error for instance %s: %s", instance_name, exc)
        return _error_response(request_id, INTERNAL_ERROR, f"MCP proxy error: {exc}")


async def _dispatch_method(session: Any, method: str, params: dict[str, Any]) -> Any:
    """Route a JSON-RPC method to the appropriate MCP SDK call."""

    if method == "tools/list":
        result = await session.list_tools()
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema if t.inputSchema else {},
                }
                for t in result.tools
            ]
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        if not tool_name:
            raise ValueError("Missing required parameter 'name' for tools/call")
        arguments = params.get("arguments", {})
        result = await session.call_tool(tool_name, arguments)
        return {
            "content": [
                {"type": c.type, "text": getattr(c, "text", None)} for c in result.content
            ],
            "isError": getattr(result, "isError", False),
        }

    elif method == "resources/list":
        result = await session.list_resources()
        return {
            "resources": [
                {
                    "uri": str(r.uri),
                    "name": r.name,
                    "description": getattr(r, "description", None),
                    "mimeType": getattr(r, "mimeType", None),
                }
                for r in result.resources
            ]
        }

    elif method == "resources/read":
        uri = params.get("uri")
        if not uri:
            raise ValueError("Missing required parameter 'uri' for resources/read")
        result = await session.read_resource(uri)
        return {
            "contents": [
                {
                    "uri": str(c.uri),
                    "mimeType": getattr(c, "mimeType", None),
                    "text": getattr(c, "text", None),
                }
                for c in result.contents
            ]
        }

    elif method == "prompts/list":
        result = await session.list_prompts()
        return {
            "prompts": [
                {
                    "name": p.name,
                    "description": getattr(p, "description", None),
                    "arguments": [
                        {
                            "name": a.name,
                            "description": getattr(a, "description", None),
                            "required": getattr(a, "required", False),
                        }
                        for a in (p.arguments or [])
                    ],
                }
                for p in result.prompts
            ]
        }

    elif method == "prompts/get":
        prompt_name = params.get("name")
        if not prompt_name:
            raise ValueError("Missing required parameter 'name' for prompts/get")
        arguments = params.get("arguments", {})
        result = await session.get_prompt(prompt_name, arguments)
        return {
            "description": getattr(result, "description", None),
            "messages": [
                {
                    "role": m.role,
                    "content": {"type": m.content.type, "text": getattr(m.content, "text", None)},
                }
                for m in result.messages
            ],
        }

    # Should not be reachable due to whitelist check above
    raise ValueError(f"Unhandled method: {method}")  # pragma: no cover
