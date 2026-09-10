"""Secret manager configuration."""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class SecretManagerSettings(BaseAppSettings):
    """Secret manager configuration.

    Supported AGENTAREA_SECRET_BACKEND values:
    - "database": Encrypted storage in PostgreSQL (default for open source)
    - "infisical": External secret management service

    One backend is active at a time, so the connection fields are named for
    their role rather than for the vendor that happens to provide it.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_SECRET_")

    BACKEND: str = "database"
    ENCRYPTION_KEY: str | None = None  # Required when AGENTAREA_SECRET_BACKEND="database"

    # Only used when AGENTAREA_SECRET_BACKEND="infisical"
    ENDPOINT: str | None = None
    CLIENT_ID: str | None = None
    CLIENT_SECRET: str | None = None
    # Which Infisical project and environment hold the secrets. Both were
    # hardcoded to "default" — a value Infisical does not issue — so no
    # deployment ever read or wrote what it meant to.
    PROJECT_ID: str = ""
    ENV: str = "prod"


@lru_cache
def get_secret_manager_settings() -> SecretManagerSettings:
    """Get secret manager settings."""
    return SecretManagerSettings()
