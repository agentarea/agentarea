"""Shared MCP server and instance transport specification helpers."""

from __future__ import annotations

from typing import Any

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
    """Build the effective transport fields declared by an MCP server row."""
    spec = dict(server.json_spec or {})
    if server.remote_url:
        spec.setdefault("type", "url")
        spec.setdefault("endpoint_url", server.remote_url)
    elif server.cmd:
        spec.setdefault("type", "command")
        spec.setdefault("command", server.cmd[0] if server.cmd else "")
        if len(server.cmd or []) > 1:
            spec.setdefault("args", list(server.cmd[1:]))
    elif server.docker_image_url:
        spec.setdefault("type", "docker")
        spec.setdefault("image", server.docker_image_url)
    else:
        spec.setdefault("type", "docker")
    return _normalize_url_keys(spec)


def merge_transport_spec(
    server_spec: dict[str, Any] | None,
    instance_spec: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge server defaults while isolating converted package transports."""
    server = dict(server_spec or {})
    instance = dict(instance_spec or {})
    image = instance.get("image")
    is_converted_docker = (
        instance.get("type") == "docker" and isinstance(image, str) and bool(image.strip())
    )
    if not is_converted_docker:
        return {**server, **instance}

    merged = {key: value for key, value in server.items() if key not in _CONVERTED_TRANSPORT_KEYS}
    merged.update(instance)
    return merged
