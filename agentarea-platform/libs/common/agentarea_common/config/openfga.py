"""OpenFGA authorization graph configuration."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings
from .duration import Duration


class OpenFGASettings(BaseAppSettings):
    """OpenFGA connection settings.

    OpenFGA is the preferred Zanzibar-style graph backend for new capability
    authorization work. Keto remains supported as a fallback during migration.

    ``FGA_`` is OpenFGA's own abbreviation — their CLI reads ``FGA_API_URL``
    and ``FGA_STORE_ID``.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_AUTHZ_FGA_")

    URL: str = "http://openfga:8080"
    STORE_ID: str = ""
    MODEL_ID: str | None = None
    TIMEOUT: Duration = timedelta(seconds=10)
    BOOTSTRAP: bool = False
    APPLY_MODEL: bool = False
    STORE_NAME: str = "agentarea"
    MODEL_PATH: str | None = None
