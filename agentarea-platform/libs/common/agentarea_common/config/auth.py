"""Authentication settings configuration.

These settings are only required by services that verify JWTs (e.g. the API).
Services like the Temporal worker that don't perform auth can skip these.
"""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class AuthSettings(BaseAppSettings):
    """Ory (Kratos and Hydra) authentication configuration.

    All fields are required — services that need JWT verification
    must have these env vars set. Services that don't (e.g. worker)
    should never instantiate this class.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_AUTH_")

    JWKS_B64: str = ""
    ISSUER: str = "http://localhost:4433"
    AUDIENCE: str = "agentarea-api"
    # Admin API, used to resolve member ids into names/emails. Blanking it
    # leaves members rendered as raw ids.
    KRATOS_ADMIN_URL: str = "http://kratos:4434"

    HYDRA_URL: str = "http://hydra:4444"
    HYDRA_ADMIN_URL: str = "http://hydra:4445"
    HYDRA_BROWSER_URL: str = "http://localhost:4444"
    # Expected audience for Hydra-issued OAuth tokens. When set, the API
    # enforces the `aud` claim (rejecting tokens minted for other clients).
    # Required to accept Hydra-issued tokens at all. Unset does NOT mean
    # "verify without an audience" any more — it means Hydra bearer tokens are
    # refused outright, so a deployment that does not run Hydra is unaffected
    # while one that does must declare which audience it accepts.
    HYDRA_AUDIENCE: str | None = None


@lru_cache
def get_auth_settings() -> AuthSettings:
    """Get authentication settings.

    Raises ValidationError if AGENTAREA_AUTH_JWKS_B64 is not set.
    Only call this from services that need JWT verification.
    """
    return AuthSettings()
