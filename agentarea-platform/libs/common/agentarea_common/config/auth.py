"""Authentication settings configuration.

These settings are only required by services that verify JWTs (e.g. the API).
Services like the Temporal worker that don't perform auth can skip these.
"""

from functools import lru_cache

from .base import BaseAppSettings


class AuthSettings(BaseAppSettings):
    """Kratos authentication configuration.

    All fields are required — services that need JWT verification
    must have these env vars set. Services that don't (e.g. worker)
    should never instantiate this class.
    """

    KRATOS_JWKS_B64: str
    KRATOS_ISSUER: str = "https://agentarea.dev"
    KRATOS_AUDIENCE: str = "agentarea-api"


@lru_cache
def get_auth_settings() -> AuthSettings:
    """Get authentication settings.

    Raises ValidationError if KRATOS_JWKS_B64 is not set.
    Only call this from services that need JWT verification.
    """
    return AuthSettings()
