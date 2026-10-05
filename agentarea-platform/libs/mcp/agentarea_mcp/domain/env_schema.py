"""Helpers for the environment and header inputs declared by MCP packages."""

from typing import Any


def normalize_env_schema(entries: Any) -> list[dict[str, Any]]:
    """Normalize MCP KeyValueInput fields for API/UI and secret routing."""
    if not isinstance(entries, list):
        return []

    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        required_value = entry.get("isRequired")
        if required_value is None:
            required_value = entry.get("required", False)
        required = bool(required_value)
        is_secret = bool(entry.get("isSecret", False))
        field: dict[str, Any] = {
            "name": name,
            "description": entry.get("description") or "",
            "isSecret": is_secret,
            "isRequired": required,
            "required": required,
        }
        if not is_secret and "default" in entry:
            field["default"] = entry["default"]
        normalized.append(field)
    return normalized


def derive_env_schema_from_spec(spec: Any) -> list[dict[str, Any]]:
    """Read a normalized schema or derive one from official MCP package inputs."""
    if not isinstance(spec, dict):
        return []

    declared = normalize_env_schema(spec.get("env_schema"))
    if declared:
        return declared

    raw_spec = spec.get("raw_spec")
    if not isinstance(raw_spec, dict):
        raw_spec = spec

    connection_type = spec.get("connection_type")
    if connection_type == "url":
        remotes = raw_spec.get("remotes")
        if not isinstance(remotes, list):
            return []
        url = spec.get("url")
        matching = [remote for remote in remotes if isinstance(remote, dict)]
        if url:
            by_url = [remote for remote in matching if remote.get("url") == url]
            if by_url:
                matching = by_url
            elif len(matching) != 1:
                return []
        elif len(matching) != 1:
            return []
        return normalize_env_schema(matching[0].get("headers"))

    if connection_type not in {"command", "docker"}:
        return []
    packages = raw_spec.get("packages")
    if not isinstance(packages, list):
        return []

    registry = spec.get("package_registry")
    package_name = spec.get("package_name") or spec.get("image")
    candidates = [
        package
        for package in packages
        if isinstance(package, dict) and (not registry or package.get("registryType") == registry)
    ]
    if package_name:
        matching = [
            package
            for package in candidates
            if package.get("name") == package_name or package.get("identifier") == package_name
        ]
        if matching:
            candidates = matching
        elif len(candidates) != 1:
            return []
    elif len(candidates) != 1:
        return []

    if len(candidates) != 1:
        return []
    return normalize_env_schema(candidates[0].get("environmentVariables"))
