"""Access-control backend selection."""

from typing import Literal

from .base import BaseAppSettings


class AccessControlSettings(BaseAppSettings):
    """Provider-neutral access-control configuration."""

    ACCESS_CONTROL_BACKEND: Literal["disabled", "keto", "openfga"] = "disabled"
