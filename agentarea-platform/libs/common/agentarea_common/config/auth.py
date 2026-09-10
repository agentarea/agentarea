"""Authentication settings configuration.

These settings are only required by services that verify JWTs (e.g. the API).
Services like the Temporal worker that don't perform auth can skip these.
"""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class AuthSettings(BaseAppSettings):
    """Kratos authentication configuration.

    All fields are required — services that need JWT verification
    must have these env vars set. Services that don't (e.g. worker)
    should never instantiate this class.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_AUTH_")

    JWKS_B64: str = ""
    ISSUER: str = "http://localhost:4433"
    AUDIENCE: str = "agentarea-api"


@lru_cache
def get_auth_settings() -> AuthSettings:
    """Get authentication settings.

    Raises ValidationError if AGENTAREA_AUTH_JWKS_B64 is not set.
    Only call this from services that need JWT verification.
    """
    return AuthSettings()
