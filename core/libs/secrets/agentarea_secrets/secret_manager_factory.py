"""Secret Manager Factory.

This module provides a factory for creating workspace-scoped secret manager
instances based on settings configuration.

Supported secret managers:
- Database: Encrypted storage in PostgreSQL (default for open source)
- Infisical: External secret management service
"""

import logging

from agentarea_common.auth import UserContext
from agentarea_common.config.secrets import SecretManagerSettings
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SecretManagerFactory:
    """Factory for creating workspace-scoped secret managers.

    This factory uses settings to determine the secret manager type
    and creates properly scoped instances with user context.
    """

    def __init__(self, settings: SecretManagerSettings):
        """Initialize factory with settings.

        Args:
            settings: Secret manager configuration settings

        Raises:
            ValueError: If required configuration is missing
        """
        self.settings = settings

        # Validate configuration at startup to fail fast
        secret_type = settings.SECRET_MANAGER_TYPE.lower()

        if secret_type == "database":
            if not settings.SECRET_MANAGER_ENCRYPTION_KEY:
                raise ValueError(
                    "SECRET_MANAGER_ENCRYPTION_KEY environment variable must be set when using database secret manager. "
                    "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
                )
        elif secret_type == "infisical":
            if not settings.SECRET_MANAGER_ACCESS_KEY or not settings.SECRET_MANAGER_SECRET_KEY:
                raise ValueError(
                    "Infisical credentials not configured. "
                    "Set SECRET_MANAGER_ACCESS_KEY and SECRET_MANAGER_SECRET_KEY."
                )

        logger.info(f"Initialized SecretManagerFactory with type: {settings.SECRET_MANAGER_TYPE}")

    def create(
        self,
        session: AsyncSession,
        user_context: UserContext,
    ) -> BaseSecretManager:
        """Create secret manager with proper workspace context.

        Args:
            session: Database session
            user_context: User context with workspace_id

        Returns:
            BaseSecretManager: Configured secret manager instance

        Raises:
            ValueError: If invalid configuration or missing dependencies
        """
        secret_type = self.settings.SECRET_MANAGER_TYPE.lower()

        if secret_type == "database":
            from .database_secret_manager import DatabaseSecretManager

            logger.debug(
                f"Creating DatabaseSecretManager for workspace {user_context.workspace_id}"
            )
            return DatabaseSecretManager(
                session=session,
                user_context=user_context,
                encryption_key=self.settings.SECRET_MANAGER_ENCRYPTION_KEY,
            )

        elif secret_type == "infisical":
            try:
                from infisical_sdk.client import InfisicalSDKClient

                from .infisical_secret_manager import InfisicalSecretManager

                if (
                    not self.settings.SECRET_MANAGER_ACCESS_KEY
                    or not self.settings.SECRET_MANAGER_SECRET_KEY
                ):
                    raise ValueError(
                        "Infisical credentials not configured. "
                        "Set SECRET_MANAGER_ACCESS_KEY and SECRET_MANAGER_SECRET_KEY."
                    )

                client = InfisicalSDKClient(
                    host=self.settings.SECRET_MANAGER_ENDPOINT
                    or "https://app.infisical.com",
                    client_id=self.settings.SECRET_MANAGER_ACCESS_KEY,
                    client_secret=self.settings.SECRET_MANAGER_SECRET_KEY,
                )

                logger.debug("Created InfisicalSecretManager")
                return InfisicalSecretManager(client)

            except ImportError as e:
                raise ValueError(
                    "Infisical SDK not installed. Install with: pip install infisical-sdk"
                ) from e

        else:
            raise ValueError(
                f"Invalid SECRET_MANAGER_TYPE: '{secret_type}'. "
                f"Supported types: 'database', 'infisical'"
            )


# Backward compatibility functions - keep old API but use factory internally


def get_secret_manager(
    secret_manager_type: str,
    session: AsyncSession | None = None,
    user_context: UserContext | None = None,
) -> BaseSecretManager:
    """Create a secret manager instance based on configuration.

    Legacy function - use SecretManagerFactory directly for better control.

    Args:
        secret_manager_type: Type of secret manager ("database" or "infisical")
        session: Database session (required)
        user_context: User context (required)

    Returns:
        BaseSecretManager: Configured secret manager instance

    Raises:
        ValueError: If invalid secret manager type or missing dependencies
    """
    if session is None or user_context is None:
        raise ValueError(
            "Database secret manager requires both 'session' and 'user_context' parameters"
        )

    from agentarea_common.config.secrets import get_secret_manager_settings

    settings = get_secret_manager_settings()
    factory = SecretManagerFactory(settings)

    return factory.create(session=session, user_context=user_context)


def get_real_secret_manager(
    session: AsyncSession | None = None,
    user_context: UserContext | None = None,
) -> BaseSecretManager:
    """Get a real secret manager implementation based on configuration.

    This function creates a secret manager instance using the configured type
    from settings. It REQUIRES both session and user_context to create a
    workspace-scoped secret manager.

    Args:
        session: Database session (REQUIRED)
        user_context: User context with workspace_id (REQUIRED)

    Returns:
        BaseSecretManager: Configured secret manager instance

    Raises:
        ValueError: If session or user_context is missing
    """
    if session is None or user_context is None:
        raise ValueError(
            "Cannot create secret manager without session and user_context. "
            "Secret manager must be created at activity level, not worker level."
        )

    from agentarea_common.config.secrets import get_secret_manager_settings

    settings = get_secret_manager_settings()
    factory = SecretManagerFactory(settings)
    return factory.create(session=session, user_context=user_context)
