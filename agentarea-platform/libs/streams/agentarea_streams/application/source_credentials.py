"""A source's credentials: one JSON object in the secret store, read at use.

Stored at ``channel_cred:{slug}:{credential_key}``. A field holds its value, or
``{"secret_name": ...}`` naming the workspace secret the member picked, whose
value is read when it is needed and never copied.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
from typing import Any, Protocol
from uuid import UUID

from ..domain.source_types import SourceField

logger = logging.getLogger(__name__)


class SecretReader(Protocol):
    async def get_secret(self, secret_name: str, /) -> str | None: ...


class CredentialsUnavailableError(Exception):
    """The source's credentials exist but cannot be used: refuse, never accept unverified."""


class SecretStoreUnreachableError(CredentialsUnavailableError):
    """The secret store did not answer; the sender should retry."""


def issue_credential(field: SourceField) -> str:
    """A value the platform generates for an ``issued`` field the member left empty."""
    if field.format == "whsec":
        return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    return secrets.token_urlsafe(32)


def credential_secret_name(slug: str, credential_key: UUID | str) -> str:
    """The one place that knows where a source's credentials are stored."""
    return f"channel_cred:{slug}:{credential_key}"


async def _read(reader: SecretReader, name: str, what: str) -> str | None:
    try:
        return await reader.get_secret(name)
    except Exception as error:
        # Neither the secret name nor the credential field in the log.
        logger.error("Reading source credentials from the secret store failed", exc_info=True)
        raise SecretStoreUnreachableError(what) from error


async def read_source_credentials(
    reader: SecretReader, slug: str, credential_key: UUID | str
) -> dict[str, str]:
    """Every credential of the source as text; referenced secrets resolved. Empty when none."""
    what = f"credentials of {slug} source {credential_key}"
    raw = await _read(reader, credential_secret_name(slug, credential_key), what)
    if not raw:
        return {}
    try:
        stored: Any = json.loads(raw)
    except ValueError as error:
        logger.error("Stored %s are not JSON", what, exc_info=True)
        raise CredentialsUnavailableError(what) from error
    if not isinstance(stored, dict):
        raise CredentialsUnavailableError(f"stored {what} are not an object")
    resolved: dict[str, str] = {}
    for key, value in stored.items():
        if isinstance(value, dict):
            name = value.get("secret_name")
            if not isinstance(name, str) or not name:
                raise CredentialsUnavailableError(f"{key} of {what} names no secret")
            secret = await _read(reader, name, f"the secret {key} of {what} names")
            if not secret:
                raise CredentialsUnavailableError(f"the secret {key} of {what} names has no value")
            resolved[key] = secret
        elif value not in (None, ""):
            resolved[key] = str(value)
    return resolved
