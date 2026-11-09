"""An instance env var or header whose value is a workspace secret, referenced by name.

``json_spec.environment`` and ``json_spec.headers`` hold either the value or
``{"secret_name": ...}``, the shape stream source credentials use. A reference
is kept in the spec as is and read at use, in the instance's own workspace;
nothing is copied into a per-instance secret for it.
"""

from __future__ import annotations

from typing import Any

SECRET_REF_KEY = "secret_name"  # noqa: S105 - the reference's key, not a credential
SECRET_REF_FIELDS = ("environment", "headers")
SECRET_REF_CONSUMER = "mcp_instance"  # noqa: S105 - a consumer type, not a credential


class InvalidSecretRefError(ValueError):
    """An object value that is not ``{"secret_name": "<name>"}``."""


class SecretRefUnresolvedError(LookupError):
    """A referenced secret has no value in the instance's workspace."""


def secret_ref(name: str) -> dict[str, str]:
    return {SECRET_REF_KEY: name}


def is_secret_ref(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get(SECRET_REF_KEY), str)


def secret_ref_name(field: str, value: Any) -> str | None:
    """The secret ``value`` references, or None when it is a literal."""
    if not isinstance(value, dict):
        return None
    name = value.get(SECRET_REF_KEY)
    if set(value) != {SECRET_REF_KEY} or not isinstance(name, str) or not name.strip():
        raise InvalidSecretRefError(
            f'{field} must be a string or {{"{SECRET_REF_KEY}": "<workspace secret>"}}'
        )
    return name


def spec_secret_refs(
    spec: dict[str, Any], fields: tuple[str, ...] = SECRET_REF_FIELDS
) -> dict[str, str]:
    """Every env var or header name in ``spec`` that references a secret, and the secret."""
    refs: dict[str, str] = {}
    for field in fields:
        values = spec.get(field)
        if not isinstance(values, dict):
            continue
        for name, value in values.items():
            secret = secret_ref_name(str(name), value)
            if secret is not None:
                refs[str(name)] = secret
    return refs


def carries_secret_ref(value: Any) -> bool:
    """Whether ``value`` holds a secret reference at any depth.

    A server spec is shared and editable by whoever may edit it, while a
    reference is authorized against the instance that carries it; so no layer
    but an instance's own environment and headers may hold one.
    """
    if isinstance(value, dict):
        return SECRET_REF_KEY in value or any(carries_secret_ref(v) for v in value.values())
    if isinstance(value, list):
        return any(carries_secret_ref(v) for v in value)
    return False


def has_secret_refs(spec: dict[str, Any]) -> bool:
    """Whether a stored spec references any secret; never raises on a row read back."""
    return any(
        is_secret_ref(value)
        for field in SECRET_REF_FIELDS
        if isinstance(spec.get(field), dict)
        for value in spec[field].values()
    )
