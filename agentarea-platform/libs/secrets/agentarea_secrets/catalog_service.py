"""Workspace-scoped operations on the secret catalog.

The split against BaseSecretManager: that interface is the value store — it
encrypts, decrypts, and knows nothing about who owns a secret or who uses it.
This service owns the catalog, and it is the only thing allowed to act on a
user's behalf. Everything here refuses to touch a row the platform manages,
because those rows are named after the connection that resolves them, and
`(workspace_id, secret_name)` is unique — so "creating" one is really an
overwrite of a live credential.
"""

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from agentarea_common.auth import UserContext
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EncryptedSecret, SecretReference
from .naming import validate_user_secret_name

logger = logging.getLogger(__name__)


class SecretNotFoundError(LookupError):
    """No such secret in this workspace."""


class ManagedSecretError(PermissionError):
    """The secret belongs to a connection, so it is not the user's to change."""


class SecretInUseError(RuntimeError):
    """Something still resolves this secret."""

    def __init__(self, consumers: list["ConsumerRef"]) -> None:
        self.consumers = consumers
        listed = ", ".join(f"{c.consumer_type}:{c.consumer_id}" for c in consumers) or "unknown"
        super().__init__(f"Secret is still used by {listed}")


class DuplicateSecretNameError(ValueError):
    """That name is taken in this workspace."""


@dataclass(frozen=True)
class ConsumerRef:
    consumer_type: str
    consumer_id: str
    field: str


class SecretCatalogService:
    def __init__(
        self,
        session: AsyncSession,
        user_context: UserContext,
        secret_manager: BaseSecretManager,
    ) -> None:
        self._session = session
        self._user_context = user_context
        self._workspace_id = user_context.workspace_id
        self._secrets = secret_manager

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def list_user_secrets(self) -> list[EncryptedSecret]:
        """Secrets the user created. Managed rows are the platform's business."""
        result = await self._session.execute(
            select(EncryptedSecret)
            .where(
                EncryptedSecret.workspace_id == self._workspace_id,
                EncryptedSecret.owner_type.is_(None),
            )
            .order_by(EncryptedSecret.secret_name)
        )
        return list(result.scalars().all())

    async def get(self, secret_id: UUID) -> EncryptedSecret:
        result = await self._session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.id == secret_id,
                EncryptedSecret.workspace_id == self._workspace_id,
            )
        )
        secret = result.scalar_one_or_none()
        if secret is None:
            raise SecretNotFoundError(f"No secret {secret_id} in this workspace")
        return secret

    async def get_by_name(self, name: str) -> EncryptedSecret:
        result = await self._session.execute(
            select(EncryptedSecret).where(
                EncryptedSecret.secret_name == name,
                EncryptedSecret.workspace_id == self._workspace_id,
            )
        )
        secret = result.scalar_one_or_none()
        if secret is None:
            raise SecretNotFoundError(f"No secret named '{name}' in this workspace")
        return secret

    async def consumers(self, secret_id: UUID) -> list[ConsumerRef]:
        """Who resolves this secret.

        Consumers declare themselves here rather than the catalog going looking
        for them: the catalog sits underneath every library that stores a
        credential, so a query per consumer table would mean depending on all of
        them — and `agentarea_llm` already depends on this package.

        This index is for display. The delete guard is the foreign key, which
        holds whether or not a consumer remembered to register.
        """
        rows = await self._session.execute(
            select(
                SecretReference.consumer_type,
                SecretReference.consumer_id,
                SecretReference.field,
            ).where(
                SecretReference.secret_id == secret_id,
                SecretReference.workspace_id == self._workspace_id,
            )
        )
        return [ConsumerRef(r.consumer_type, r.consumer_id, r.field) for r in rows]

    # ------------------------------------------------------------------
    # Writes — user-owned secrets only
    # ------------------------------------------------------------------

    async def create_user_secret(
        self, name: str, value: str, description: str | None = None
    ) -> EncryptedSecret:
        validate_user_secret_name(name)

        existing = await self._session.execute(
            select(EncryptedSecret.id).where(
                EncryptedSecret.workspace_id == self._workspace_id,
                EncryptedSecret.secret_name == name,
            )
        )
        if existing.scalar_one_or_none() is not None:
            # set_secret would update it. For a create that is the wrong answer:
            # the caller believes it is making a new secret.
            raise DuplicateSecretNameError(f"A secret named '{name}' already exists")

        # Only the database backend leaves a catalog row behind as a side effect
        # of storing the value — for it, the row and the store are the same
        # thing. Every other backend writes the value elsewhere and the catalog
        # has to create the row itself, or the secret would exist in Infisical
        # with nothing here describing it.
        ref = self._secrets.external_ref(name)
        await self._secrets.set_secret(name, value)

        if ref is None:
            await self._session.execute(
                update(EncryptedSecret)
                .where(
                    EncryptedSecret.workspace_id == self._workspace_id,
                    EncryptedSecret.secret_name == name,
                )
                .values(description=description)
            )
        else:
            self._session.add(
                EncryptedSecret(
                    id=uuid4(),
                    workspace_id=self._workspace_id,
                    secret_name=name,
                    encrypted_value=None,
                    external_ref=ref,
                    description=description,
                    created_by=self._user_context.user_id,
                )
            )
        await self._session.commit()

        logger.info("Created user secret in workspace %s", self._workspace_id)
        return await self.get_by_name(name)

    async def rotate_user_secret(self, secret_id: UUID, value: str) -> EncryptedSecret:
        secret = await self._require_user_owned(secret_id)
        await self._secrets.set_secret(secret.secret_name, value)

        if secret.external_ref is not None:
            # The backend took the new value; the row it does not own still has
            # to reflect that something changed.
            await self._session.execute(
                update(EncryptedSecret)
                .where(EncryptedSecret.id == secret.id)
                .values(updated_by=self._user_context.user_id)
            )
            await self._session.commit()

        await self._session.refresh(secret)
        logger.info("Rotated user secret in workspace %s", self._workspace_id)
        return secret

    async def update_description(self, secret_id: UUID, description: str | None) -> EncryptedSecret:
        secret = await self._require_user_owned(secret_id)
        await self._session.execute(
            update(EncryptedSecret)
            .where(EncryptedSecret.id == secret.id)
            .values(description=description, updated_by=self._user_context.user_id)
        )
        await self._session.commit()
        return await self.get(secret_id)

    async def delete_user_secret(self, secret_id: UUID) -> None:
        secret = await self._require_user_owned(secret_id)

        try:
            await self._session.execute(
                delete(EncryptedSecret).where(EncryptedSecret.id == secret.id)
            )
            await self._session.commit()
        except IntegrityError:
            # RESTRICT on secret_references.secret_id. The database is the guard
            # rather than a check up front, so a reference created concurrently
            # cannot slip through between the check and the delete.
            await self._session.rollback()
            raise SecretInUseError(await self.consumers(secret_id)) from None

        if secret.external_ref is not None:
            # Dropping the row removed the value only when the row *was* the
            # value. Otherwise the credential is still sitting in the backend
            # with nothing left pointing at it.
            await self._secrets.delete_secret(secret.secret_name)

        logger.info("Deleted user secret from workspace %s", self._workspace_id)

    async def _require_user_owned(self, secret_id: UUID) -> EncryptedSecret:
        secret = await self.get(secret_id)
        if secret.owner_type is not None:
            raise ManagedSecretError(
                f"Secret '{secret.secret_name}' is managed by "
                f"{secret.owner_type} {secret.owner_id}. Change it there instead."
            )
        return secret

    # ------------------------------------------------------------------
    # References, for consumers that keep theirs inside a JSON document
    # ------------------------------------------------------------------

    async def add_reference(
        self, secret_id: UUID, consumer_type: str, consumer_id: str, field: str
    ) -> None:
        await self.get(secret_id)  # workspace check
        existing = await self._session.execute(
            select(SecretReference.id).where(
                SecretReference.secret_id == secret_id,
                SecretReference.consumer_type == consumer_type,
                SecretReference.consumer_id == consumer_id,
                SecretReference.field == field,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        self._session.add(
            SecretReference(
                workspace_id=self._workspace_id,
                secret_id=secret_id,
                consumer_type=consumer_type,
                consumer_id=consumer_id,
                field=field,
            )
        )
        await self._session.commit()

    async def clear_references(self, consumer_type: str, consumer_id: str) -> None:
        """Drop every reference a consumer holds, before rewriting them."""
        await self._session.execute(
            delete(SecretReference).where(
                SecretReference.workspace_id == self._workspace_id,
                SecretReference.consumer_type == consumer_type,
                SecretReference.consumer_id == consumer_id,
            )
        )
        await self._session.commit()

    async def count_user_secrets(self) -> int:
        result = await self._session.execute(
            select(func.count(EncryptedSecret.id)).where(
                EncryptedSecret.workspace_id == self._workspace_id,
                EncryptedSecret.owner_type.is_(None),
            )
        )
        return int(result.scalar_one())
