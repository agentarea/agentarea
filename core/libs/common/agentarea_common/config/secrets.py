"""Secret manager configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class SecretManagerSettings(BaseAppSettings):
    """Secret manager configuration."""

    SECRET_MANAGER_TYPE: str = "local"
    SECRET_MANAGER_ENDPOINT: str | None = None
    SECRET_MANAGER_ACCESS_KEY: str | None = None
    SECRET_MANAGER_SECRET_KEY: str | None = None


@lru_cache
def get_secret_manager_settings() -> SecretManagerSettings:
    """Get secret manager settings."""
    return SecretManagerSettings()
