"""Database-backed secret manager with encryption.

This implementation stores secrets in a PostgreSQL database table with Fernet
symmetric encryption. Suitable for production use in self-hosted deployments.
"""

import logging
import uuid

from agentarea_common.auth import UserContext
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from cryptography.fernet import Fernet
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from .models import EncryptedSecret
from .naming import parse_managed_name

logger = logging.getLogger(__name__)

__all__ = ["DatabaseSecretManager", "EncryptedSecret"]


class DatabaseSecretManager(BaseSecretManager):
    """Database-backed secret manager with Fernet encryption.

    Stores secrets in a PostgreSQL table with symmetric encryption.
    Secrets are scoped by workspace for multi-tenancy support.
    """

    def __init__(
        self,
        session: AsyncSession,
        user_context: UserContext,
        encryption_key: str | None = None,
    ):
        """Initialize database secret manager.

        Args:
            session: SQLAlchemy async session for database operations
            user_context: User context for workspace scoping and audit trail
            encryption_key: Fernet encryption key (required; set SECRET_MANAGER_ENCRYPTION_KEY env var)
        """
        self.session = session
        self.user_context = user_context
        self.workspace_id = user_context.workspace_id

        # Initialize encryption
        self._fernet = self._load_or_create_key(encryption_key)

        logger.info(f"Initialized DatabaseSecretManager for workspace {self.workspace_id}")

    def _load_or_create_key(self, encryption_key: str | None) -> Fernet:
        """Load or create a symmetric encryption key.

        Args:
            encryption_key: Encryption key from settings (required)

        Returns:
            Fernet instance for encryption/decryption

        Raises:
            ValueError: If no encryption key is provided
        """
        if not encryption_key:
            # Fail fast - encryption key is required
            raise ValueError(
                "Encryption key is required for DatabaseSecretManager. "
                "This should have been validated at SecretManagerFactory initialization."
            )

        key = encryption_key.encode("utf-8")
        logger.info("Using provided encryption key")
        return Fernet(key)

    def _encrypt(self, value: str) -> str:
        """Encrypt a secret value.

        Args:
            value: Plain text secret value

        Returns:
            Encrypted value as string
        """
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        """Decrypt a secret value.

        Args:
            value: Encrypted secret value

        Returns:
            Decrypted plain text value
        """
        try:
            return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            logger.error("Failed to decrypt secret value")
            raise ValueError("Failed to decrypt secret. Key may have changed.") from exc

    def external_ref(self, secret_name: str) -> None:
        """None: this backend keeps the value in the catalog row itself."""
        return None

    async def get_secret(self, secret_name: str) -> str | None:
        """Get a secret value by name.

        Args:
            secret_name: Name of the secret to retrieve

        Returns:
            Decrypted secret value or None if not found
        """
        try:
            result = await self.session.execute(
                select(EncryptedSecret).where(
                    EncryptedSecret.workspace_id == self.workspace_id,
                    EncryptedSecret.secret_name == secret_name,
                )
            )
            secret = result.scalar_one_or_none()

            if secret is None:
                logger.debug("Secret not found in workspace %s", self.workspace_id)
                return None

            if secret.encrypted_value is None:
                # The row points at an external store, which this backend cannot
                # read. Saying "not found" would send the caller looking for a
                # missing secret instead of a misconfigured backend.
                raise ValueError(
                    f"Secret '{secret_name}' is backed by an external provider; "
                    "the database secret manager cannot resolve it."
                )

            decrypted_value = self._decrypt(secret.encrypted_value)
            logger.debug("Retrieved secret from workspace %s", self.workspace_id)
            return decrypted_value

        except Exception as exc:
            logger.error(
                "Failed to retrieve secret from workspace %s (%s)",
                self.workspace_id,
                type(exc).__name__,
            )
            raise

    async def set_secret(self, secret_name: str, secret_value: str) -> None:
        """Set a secret value (create or update).

        Args:
            secret_name: Name of the secret to set
            secret_value: Plain text secret value to encrypt and store
        """
        try:
            encrypted_value = self._encrypt(secret_value)

            # Check if secret already exists
            result = await self.session.execute(
                select(EncryptedSecret).where(
                    EncryptedSecret.workspace_id == self.workspace_id,
                    EncryptedSecret.secret_name == secret_name,
                )
            )
            existing_secret = result.scalar_one_or_none()

            if existing_secret:
                # Update existing secret. Ownership is not re-derived: the name
                # has not changed, and a row the catalog has since re-classified
                # should not be silently reverted by a routine value rotation.
                await self.session.execute(
                    update(EncryptedSecret)
                    .where(
                        EncryptedSecret.workspace_id == self.workspace_id,
                        EncryptedSecret.secret_name == secret_name,
                    )
                    .values(
                        encrypted_value=encrypted_value,
                        external_ref=None,
                        updated_by=self.user_context.user_id,
                        updated_at=func.now(),
                    )
                )
                logger.info("Updated secret in workspace %s", self.workspace_id)
            else:
                # Names minted by a platform producer carry their owner, so the
                # catalog can classify the row without every caller being taught
                # to declare one. Anything unrecognised is a user's own secret.
                owner = parse_managed_name(secret_name)
                new_secret = EncryptedSecret(
                    id=uuid.uuid4(),
                    workspace_id=self.workspace_id,
                    secret_name=secret_name,
                    encrypted_value=encrypted_value,
                    owner_type=owner.owner_type if owner else None,
                    owner_id=owner.owner_id if owner else None,
                    created_by=self.user_context.user_id,
                )
                self.session.add(new_secret)
                logger.info("Created secret in workspace %s", self.workspace_id)

            await self.session.commit()

        except Exception as exc:
            await self.session.rollback()
            logger.error(
                "Failed to set secret in workspace %s (%s)",
                self.workspace_id,
                type(exc).__name__,
            )
            raise

    async def delete_secret(self, secret_name: str) -> bool:
        """Delete a secret by name.

        Args:
            secret_name: Name of the secret to delete

        Returns:
            True if secret was deleted, False if it didn't exist
        """
        try:
            result = await self.session.execute(
                select(EncryptedSecret).where(
                    EncryptedSecret.workspace_id == self.workspace_id,
                    EncryptedSecret.secret_name == secret_name,
                )
            )
            secret = result.scalar_one_or_none()

            if secret is None:
                logger.debug("Secret not found for deletion in workspace %s", self.workspace_id)
                return False

            await self.session.delete(secret)
            await self.session.commit()

            logger.info("Deleted secret from workspace %s", self.workspace_id)
            return True

        except Exception as exc:
            await self.session.rollback()
            logger.error(
                "Failed to delete secret from workspace %s (%s)",
                self.workspace_id,
                type(exc).__name__,
            )
            raise
