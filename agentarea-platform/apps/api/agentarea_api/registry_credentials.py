"""Resolve a registry's credentials reference to its value, at sync time (ADR-0044).

The registry stores which secret it reads its source with, never the value; the
value is read from the owning workspace's secret store for one sync and then
dropped.
"""

from agentarea_common.auth.context import UserContext
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID
from agentarea_registry.application.service import CredentialsResolver
from agentarea_registry.domain.models import Registry
from agentarea_secrets.models import EncryptedSecret
from agentarea_secrets.secret_manager_factory import get_real_secret_manager
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# How a registry appears among a secret's consumers: names, not values.
REGISTRY_SECRET_CONSUMER = "registry"  # noqa: S105  # pragma: allowlist secret
REGISTRY_SECRET_FIELD = "credentials"  # noqa: S105  # pragma: allowlist secret


class RegistryCredentialsError(LookupError):
    """The secret a registry names is gone or holds no value."""


def registry_credentials_resolver(session: AsyncSession) -> CredentialsResolver:
    async def resolve(registry: Registry) -> str:
        workspace_id = registry.workspace_id or PLATFORM_WORKSPACE_ID
        secret = (
            await session.execute(
                select(EncryptedSecret).where(
                    EncryptedSecret.id == registry.credentials_secret_ref,
                    EncryptedSecret.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if secret is None:
            raise RegistryCredentialsError(
                f"Registry {registry.id} names a secret that is not in its workspace"
            )
        manager = get_real_secret_manager(
            session, UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=workspace_id)
        )
        value = await manager.get_secret(secret.secret_name)
        if not value:
            raise RegistryCredentialsError(
                f"Secret '{secret.secret_name}' of registry {registry.id} holds no value"
            )
        return value

    return resolve
