"""Shared MCP server and instance transport specification helpers."""

from __future__ import annotations

from typing import Any

from agentarea_mcp.domain.transport import MCPTransport

_CONVERTED_TRANSPORT_KEYS = frozenset(
    {
        "type",
        "endpoint_url",
        "url",
        "external_url",
        "internal_url",
        "image",
        "command",
        "args",
        "cmd",
        "port",
        "remote_url",
    }
)


def _normalize_url_keys(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("type") != "url":
        return spec
    if spec.get("endpoint_url"):
        return spec
    for legacy in ("url", "external_url"):
        value = spec.get(legacy)
        if isinstance(value, str) and value.strip():
            normalized = {**spec, "endpoint_url": value}
            normalized.pop(legacy, None)
            return normalized
    return spec


def server_transport_spec(server: Any) -> dict[str, Any]:
    """Build the transport fields declared by an MCP server row.

    The result has a ``type`` only when the row declares one; a row that declares
    none has no transport, and :func:`server_transport` refuses it.
    """
    spec = dict(server.json_spec or {})
    if server.remote_url:
        spec.setdefault("type", MCPTransport.URL.value)
        spec.setdefault("endpoint_url", server.remote_url)
    elif server.cmd:
        spec.setdefault("type", MCPTransport.COMMAND.value)
        spec.setdefault("command", server.cmd[0] if server.cmd else "")
        if len(server.cmd or []) > 1:
            spec.setdefault("args", list(server.cmd[1:]))
    elif server.docker_image_url:
        spec.setdefault("type", MCPTransport.DOCKER.value)
        spec.setdefault("image", server.docker_image_url)
    return _normalize_url_keys(spec)


def server_transport(server: Any) -> MCPTransport:
    """The transport an instance created from this server row gets."""
    declared = server_transport_spec(server).get("type")
    if not declared:
        raise ValueError(f"MCP server {server.id} declares no transport")
    return MCPTransport(declared)


def merge_transport_spec(
    server_spec: dict[str, Any] | None,
    instance_spec: dict[str, Any] | None,
    transport: MCPTransport,
) -> dict[str, Any]:
    """Merge server defaults under the instance's config, typed by the instance's transport.

    A package-converted instance is a docker instance carrying its own image;
    none of the server's transport keys apply to it.
    """
    server = dict(server_spec or {})
    instance = dict(instance_spec or {})
    image = instance.get("image")
    is_converted_docker = (
        transport == MCPTransport.DOCKER and isinstance(image, str) and bool(image.strip())
    )
    if is_converted_docker:
        merged = {
            key: value for key, value in server.items() if key not in _CONVERTED_TRANSPORT_KEYS
        }
        merged.update(instance)
    else:
        merged = {**server, **instance}
    merged["type"] = transport.value
    return _normalize_url_keys(merged)


def instance_transport_spec(server: Any, instance: Any) -> dict[str, Any]:
    """What an instance connects with: its server's transport fields under its own config."""
    return merge_transport_spec(
        server_transport_spec(server), instance.json_spec, MCPTransport(instance.transport)
    )
