"""Ory Keto (ReBAC) configuration."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings
from .duration import Duration


class KetoSettings(BaseAppSettings):
    """Ory Keto ReBAC connection settings.

    Powers the access explorer's relationship graph, tuple management and
    permission checks when ``AGENTAREA_AUTHZ_BACKEND=keto``.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_AUTHZ_KETO_")

    READ_URL: str = "http://keto:4466"
    WRITE_URL: str = "http://keto:4467"
    TIMEOUT: Duration = timedelta(seconds=10)
