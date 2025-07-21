"""Application settings configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings() 