"""Resolve user ids into human identities.

Membership lives in the relationship graph, which knows ids and nothing else.
Anything that renders a person — the members page, the members toolset — needs
a name to put next to the id, and the identity provider is the only authority
for that. An invitation's ``email`` is explicitly not that authority: it records
where a link was sent and who may redeem it, never what that person is called.

When the directory cannot answer, the identity stays unresolved. Callers render
that as an unknown user rather than substituting a plausible-looking value.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from ..config.auth import get_auth_settings

logger = logging.getLogger(__name__)

MAX_CONCURRENT_LOOKUPS = 8
DEFAULT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class IdentityRecord:
    """What the identity provider knows about a user."""

    user_id: str
    email: str | None
    display_name: str | None


@runtime_checkable
class IdentityDirectory(Protocol):
    async def resolve(self, user_ids: Sequence[str]) -> dict[str, IdentityRecord]:
        """Map each resolvable id to its identity. Unresolvable ids are absent."""
        ...


class KratosIdentityDirectory:
    """Identity lookups against the Kratos admin API."""

    def __init__(
        self,
        admin_url: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not admin_url or not admin_url.strip():
            raise ValueError("admin_url is required to resolve identities")
        self._admin_url = admin_url.strip().rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def resolve(self, user_ids: Sequence[str]) -> dict[str, IdentityRecord]:
        unique_ids = list(dict.fromkeys(user_id for user_id in user_ids if user_id))
        if not unique_ids:
            return {}

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOOKUPS)

        async with httpx.AsyncClient(
            base_url=self._admin_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:

            async def fetch(user_id: str) -> tuple[str, IdentityRecord | None]:
                async with semaphore:
                    return user_id, await self._fetch_one(client, user_id)

            results = await asyncio.gather(*(fetch(user_id) for user_id in unique_ids))

        return {user_id: record for user_id, record in results if record is not None}

    async def _fetch_one(self, client: httpx.AsyncClient, user_id: str) -> IdentityRecord | None:
        try:
            response = await client.get(f"/admin/identities/{user_id}")
        except httpx.HTTPError:
            logger.warning("Identity lookup failed for user %s", user_id, exc_info=True)
            return None

        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        if response.is_error:
            logger.warning(
                "Identity lookup for user %s returned HTTP %s",
                user_id,
                response.status_code,
            )
            return None

        try:
            traits = response.json().get("traits") or {}
        except ValueError:
            logger.warning("Identity lookup for user %s returned non-JSON", user_id, exc_info=True)
            return None

        return _record_from_traits(user_id, traits)


def _record_from_traits(user_id: str, traits: dict[str, Any]) -> IdentityRecord:
    email = traits.get("email") or None
    display_name = _display_name_from_traits(traits) or email
    return IdentityRecord(user_id=user_id, email=email, display_name=display_name)


def _display_name_from_traits(traits: dict[str, Any]) -> str | None:
    name = traits.get("name")
    if isinstance(name, dict):
        joined = " ".join(part for part in (name.get("first"), name.get("last")) if part)
        if joined:
            return joined
    elif isinstance(name, str) and name.strip():
        return name.strip()
    username = traits.get("username")
    return username.strip() if isinstance(username, str) and username.strip() else None


def identity_for(
    user_id: str,
    identities: Mapping[str, IdentityRecord],
    *,
    current_user_id: str,
    current_user_email: str | None,
) -> IdentityRecord:
    """The best available identity for one member id.

    Falls back to the caller's own verified token for the caller themselves —
    a second authority for exactly one id, not a guess about anybody else.
    Everyone the directory could not resolve comes back with empty fields.
    """
    identity = identities.get(user_id)
    email = identity.email if identity is not None else None
    display_name = identity.display_name if identity is not None else None

    if user_id == current_user_id:
        email = email or current_user_email
        display_name = display_name or email

    return IdentityRecord(user_id=user_id, email=email, display_name=display_name)


def get_identity_directory() -> IdentityDirectory | None:
    """The configured directory, or None when identity resolution is switched off."""
    admin_url = get_auth_settings().KRATOS_ADMIN_URL
    if not admin_url or not admin_url.strip():
        logger.warning("KRATOS_ADMIN_URL is unset — workspace members will render as raw ids")
        return None
    return KratosIdentityDirectory(admin_url)
