"""Secret manager configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class SecretManagerSettings(BaseAppSettings):
    """Secret manager configuration.

    Supported SECRET_MANAGER_TYPE values:
    - "database": Encrypted storage in PostgreSQL (default for open source)
    - "infisical": External secret management service
    """

    SECRET_MANAGER_TYPE: str = "database"  # noqa: S105
    SECRET_MANAGER_ENCRYPTION_KEY: str | None = None  # Required when SECRET_MANAGER_TYPE="database"

    # Infisical-specific settings (only used when SECRET_MANAGER_TYPE="infisical")
    SECRET_MANAGER_ENDPOINT: str | None = None
    SECRET_MANAGER_ACCESS_KEY: str | None = None
    SECRET_MANAGER_SECRET_KEY: str | None = None
    # Which Infisical project and environment hold the secrets. Both were
    # hardcoded to "default" — a value Infisical does not issue — so no
    # deployment ever read or wrote what it meant to.
    SECRET_MANAGER_PROJECT_ID: str = ""
    # Not a credential — an Infisical environment slug. The SECRET_* prefix is
    # what trips the hardcoded-password check.
    SECRET_MANAGER_ENVIRONMENT: str = "prod"  # noqa: S105


@lru_cache
def get_secret_manager_settings() -> SecretManagerSettings:
    """Get secret manager settings."""
    return SecretManagerSettings()
