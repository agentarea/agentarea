"""Database-backed secret manager with encryption.

This implementation stores secrets in a PostgreSQL database table with Fernet
symmetric encryption. Suitable for production use in self-hosted deployments.
"""

import logging
import uuid

from agentarea_common.auth import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)


class EncryptedSecret(BaseModel):
    """Database model for encrypted secrets."""

    __tablename__ = "encrypted_secrets"

    workspace_id: Mapped[str] = mapped_column(nullable=False, index=True)
    secret_name: Mapped[str] = mapped_column(nullable=False, index=True)
    encrypted_value: Mapped[str] = mapped_column(nullable=False)
    created_by: Mapped[str] = mapped_column(nullable=False)
    updated_by: Mapped[str | None] = mapped_column(nullable=True)


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

        logger.info("Initialized DatabaseSecretManager", extra={"workspace_id": self.workspace_id})

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
        except (InvalidToken, Exception) as e:
            logger.error("Failed to decrypt secret value", extra={"error": str(e)})
            raise ValueError("Failed to decrypt secret. Key may have changed.") from e

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
                logger.debug("Secret not found", extra={"secret_name": secret_name, "workspace_id": self.workspace_id})
                return None

            decrypted_value = self._decrypt(secret.encrypted_value)
            logger.debug("Retrieved secret", extra={"secret_name": secret_name, "workspace_id": self.workspace_id})
            return decrypted_value

        except Exception as e:
            logger.error(
                "Error retrieving secret",
                extra={"secret_name": secret_name, "workspace_id": self.workspace_id, "error": str(e)},
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
                # Update existing secret
                await self.session.execute(
                    update(EncryptedSecret)
                    .where(
                        EncryptedSecret.workspace_id == self.workspace_id,
                        EncryptedSecret.secret_name == secret_name,
                    )
                    .values(
                        encrypted_value=encrypted_value,
                        updated_by=self.user_context.user_id,
                        updated_at=func.now(),
                    )
                )
                logger.info("Updated secret", extra={"secret_name": secret_name, "workspace_id": self.workspace_id})
            else:
                # Create new secret
                new_secret = EncryptedSecret(
                    id=uuid.uuid4(),
                    workspace_id=self.workspace_id,
                    secret_name=secret_name,
                    encrypted_value=encrypted_value,
                    created_by=self.user_context.user_id,
                )
                self.session.add(new_secret)
                logger.info("Created secret", extra={"secret_name": secret_name, "workspace_id": self.workspace_id})

            await self.session.commit()

        except Exception as e:
            await self.session.rollback()
            logger.error(
                "Error setting secret",
                extra={"secret_name": secret_name, "workspace_id": self.workspace_id, "error": str(e)},
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
                logger.debug(
                    "Secret not found for deletion",
                    extra={"secret_name": secret_name, "workspace_id": self.workspace_id},
                )
                return False

            await self.session.delete(secret)
            await self.session.commit()

            logger.info("Deleted secret", extra={"secret_name": secret_name, "workspace_id": self.workspace_id})
            return True

        except Exception as e:
            await self.session.rollback()
            logger.error(
                "Error deleting secret",
                extra={"secret_name": secret_name, "workspace_id": self.workspace_id, "error": str(e)},
            )
            raise
