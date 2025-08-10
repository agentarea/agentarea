"""Application settings configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False
    DEV_MODE: bool = False  # Enable development mode for easier testing
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # OIDC Configuration for JWT authentication (deprecated - kept for backward compatibility)
    OIDC_JWKS_URI: str = ""
    OIDC_ALGORITHM: str = "RS256"
    OIDC_ISSUER: str = ""
    OIDC_AUDIENCE: str = ""

    # Clerk Configuration
    CLERK_SECRET_KEY: str = ""
    CLERK_ISSUER: str = ""
    CLERK_JWKS_URL: str = ""
    CLERK_AUDIENCE: str = ""


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings()
