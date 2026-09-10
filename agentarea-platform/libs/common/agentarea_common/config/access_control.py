"""Access-control backend selection."""

from typing import Literal

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings


class AccessControlSettings(BaseAppSettings):
    """Provider-neutral access-control configuration."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_AUTHZ_")

    BACKEND: Literal["disabled", "keto", "openfga"] = "disabled"
