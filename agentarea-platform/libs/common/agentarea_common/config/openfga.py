"""OpenFGA authorization graph configuration."""

from datetime import timedelta

from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings
from .duration import Duration


class OpenFGASettings(BaseAppSettings):
    """OpenFGA connection settings.

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
    # Bearer token sent with every request when the server runs with
    # OPENFGA_AUTHN_METHOD=preshared. Empty means the server accepts
    # unauthenticated requests (OPENFGA_AUTHN_METHOD=none, the OpenFGA default).
    API_TOKEN: str = ""
