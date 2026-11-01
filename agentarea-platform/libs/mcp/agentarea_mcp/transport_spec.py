"""Shared MCP server and instance transport specification helpers."""

from __future__ import annotations

from typing import Any, cast

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


def _image_name(reference: str) -> str:
    reference = reference.split("@", 1)[0]
    colon = reference.rfind(":")
    if colon > reference.rfind("/"):
        reference = reference[:colon]
    return reference


def image_serves_stdio(spec: dict[str, Any]) -> bool:
    """Whether a docker spec runs an image whose server speaks stdio, as its package declares.

    Such a container has no port to reach it on, and mcp-base's bridge cannot run
    inside an image it did not build. A declared port overrides the package.
    Mirrors ``mcpspec.ImageServesStdio`` in mcp-manager.
    """
    if spec.get("port") is not None:
        return False
    image = spec.get("image")
    image_name = _image_name(image) if isinstance(image, str) else None
    packages: object = spec.get("packages")
    images: list[dict[str, object]] = []
    if isinstance(packages, list):
        for package in cast(list[object], packages):
            if isinstance(package, dict):
                typed = cast(dict[str, object], package)
                if typed.get("registryType") == "oci":
                    images.append(typed)
    chosen = images[0] if len(images) == 1 else None
    for package in images:
        identifier = package.get("identifier")
        if isinstance(identifier, str) and identifier and _image_name(identifier) == image_name:
            chosen = package
            break
    transport = chosen.get("transport") if chosen else None
    return isinstance(transport, dict) and cast(dict[str, object], transport).get("type") == "stdio"


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
