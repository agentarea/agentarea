"""The credentials of the source a task replies through, read in the task's workspace.

A source keeps its credentials as one JSON object at ``channel_cred:{type}:{credential_key}``:
each field is the value, or ``{"secret_name": ...}`` naming a workspace secret that
holds it. Reads go through the task's workspace, so an address naming another
workspace's source finds nothing to send with.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from .exceptions import FatalError, RetryableError

if TYPE_CHECKING:
    from agentarea_secrets import SecretManagerFactory
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


def source_credentials_secret_name(credential_type: str, credential_key: str) -> str:
    return f"channel_cred:{credential_type}:{credential_key}"


class CredentialReader(Protocol):
    async def __call__(
        self, *, workspace_id: str, owner: str, credential_type: str, credential_key: str
    ) -> dict[str, Any]: ...


def credentials_of(address: dict[str, Any]) -> tuple[str, str]:
    """The (type, key) of the credentials an address sends with."""
    credential_type = address.get("credential_type")
    credential_key = address.get("credential_key")
    if not credential_type or not credential_key:
        raise FatalError("the delivery address names no source credentials")
    return str(credential_type), str(credential_key)


class SourceCredentialReader:
    """Reads and resolves a source's credentials, one session per read."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_manager_factory: SecretManagerFactory,
    ) -> None:
        self._session_factory = session_factory
        self._secret_manager_factory = secret_manager_factory

    async def __call__(
        self, *, workspace_id: str, owner: str, credential_type: str, credential_key: str
    ) -> dict[str, Any]:
        from agentarea_common.auth.context import UserContext
        from agentarea_common.base.tenant_scope import workspace_scope

        name = source_credentials_secret_name(credential_type, credential_key)
        async with self._session_factory() as session:
            with workspace_scope(workspace_id):
                secrets = self._secret_manager_factory.create(
                    session=session,
                    user_context=UserContext(user_id=owner, workspace_id=workspace_id),
                )
                try:
                    raw = await secrets.get_secret(name)
                except Exception as error:
                    logger.error(
                        "Reading the credentials of %s %s failed",
                        credential_type,
                        credential_key,
                        exc_info=True,
                    )
                    raise RetryableError(f"secret store: {error}") from error
                if not raw:
                    raise FatalError(
                        f"no credentials for {credential_type} source key {credential_key} "
                        f"in workspace {workspace_id}"
                    )
                try:
                    stored = json.loads(raw)
                except json.JSONDecodeError as error:
                    raise FatalError(
                        f"stored {credential_type} credentials are not JSON"
                    ) from error
                if not isinstance(stored, dict):
                    raise FatalError(f"stored {credential_type} credentials are not an object")
                resolved: dict[str, Any] = {}
                for field, value in stored.items():
                    if isinstance(value, dict):
                        resolved[field] = await _referenced(secrets, field, value)
                    else:
                        resolved[field] = value
                return resolved


async def _referenced(secrets: Any, field: str, reference: dict[str, Any]) -> str:
    name = reference.get("secret_name")
    if not isinstance(name, str) or not name:
        raise FatalError(f"credential {field} references no secret")
    try:
        value = await secrets.get_secret(name)
    except Exception as error:
        logger.error("Reading a source credential from the secret store failed", exc_info=True)
        raise RetryableError(f"secret store: {error}") from error
    if not value:
        raise FatalError(f"the secret credential {field} refers to has no value")
    return value
