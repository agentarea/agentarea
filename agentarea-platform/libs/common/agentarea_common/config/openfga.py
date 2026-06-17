"""OpenFGA authorization graph configuration."""

from .base import BaseAppSettings


class OpenFGASettings(BaseAppSettings):
    """OpenFGA connection settings.

    OpenFGA is the preferred Zanzibar-style graph backend for new capability
    authorization work. Keto remains supported as a fallback during migration.
    """

    OPENFGA_ENABLED: bool = False
    OPENFGA_API_URL: str = "http://openfga:8080"
    OPENFGA_STORE_ID: str = ""
    OPENFGA_AUTHORIZATION_MODEL_ID: str | None = None
    OPENFGA_TIMEOUT_SECONDS: float = 10.0
