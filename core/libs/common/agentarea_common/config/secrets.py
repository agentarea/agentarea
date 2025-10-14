"""Secret manager configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class SecretManagerSettings(BaseAppSettings):
    """Secret manager configuration.

    Supported SECRET_MANAGER_TYPE values:
    - "database": Encrypted storage in PostgreSQL (default for open source)
    - "infisical": External secret management service
    """

    SECRET_MANAGER_TYPE: str = "database"
    SECRET_MANAGER_ENCRYPTION_KEY: str | None = None  # For database encryption (auto-generated if None)

    # Infisical-specific settings (only used when SECRET_MANAGER_TYPE="infisical")
    SECRET_MANAGER_ENDPOINT: str | None = None
    SECRET_MANAGER_ACCESS_KEY: str | None = None
    SECRET_MANAGER_SECRET_KEY: str | None = None


@lru_cache
def get_secret_manager_settings() -> SecretManagerSettings:
    """Get secret manager settings."""
    return SecretManagerSettings()
