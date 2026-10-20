"""Resolve a registry's credentials reference to its value, at sync time (ADR-0044).

The registry stores which secret it reads its source with, never the value; the
value is read from the owning workspace's secret store for one sync and then
dropped.
"""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID
from agentarea_registry.application.service import CredentialsResolver
from agentarea_registry.domain.models import Registry
from agentarea_secrets.catalog_service import SecretCatalogService, SecretNotFoundError
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


def _platform_secrets(session: AsyncSession) -> SecretCatalogService:
    context = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=PLATFORM_WORKSPACE_ID)
    return SecretCatalogService(session, context, get_real_secret_manager(session, context))


async def platform_secret_id(session: AsyncSession, ref: str) -> UUID:
    """The id of the platform workspace's secret a manifest names, by id or by name.

    A platform registry's credentials are such a secret; the manifest names it
    and the registry keeps its id, never its value.
    """
    catalog = _platform_secrets(session)
    try:
        try:
            return (await catalog.get(UUID(ref))).id
        except ValueError:
            return (await catalog.get_by_name(ref)).id
    except SecretNotFoundError as e:
        raise RegistryCredentialsError(
            f"credentials_secret_ref {ref!r} names no secret of the platform workspace"
        ) from e


async def record_registry_secret_reference(
    session: AsyncSession, registry_id: UUID, secret_id: UUID | None
) -> None:
    """List the registry among the platform secret's consumers, or nowhere without one."""
    catalog = _platform_secrets(session)
    await catalog.clear_references(REGISTRY_SECRET_CONSUMER, str(registry_id))
    if secret_id is not None:
        await catalog.add_reference(
            secret_id, REGISTRY_SECRET_CONSUMER, str(registry_id), REGISTRY_SECRET_FIELD
        )
