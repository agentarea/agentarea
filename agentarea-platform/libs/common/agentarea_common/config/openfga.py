"""OpenFGA authorization graph configuration."""

from .base import BaseAppSettings


class OpenFGASettings(BaseAppSettings):
    """OpenFGA connection settings.

    OpenFGA is the preferred Zanzibar-style graph backend for new capability
    authorization work. Keto remains supported as a fallback during migration.
    """

    ACCESS_CONTROL_OPENFGA_API_URL: str = "http://openfga:8080"
    ACCESS_CONTROL_OPENFGA_STORE_ID: str = ""
    ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID: str | None = None
    ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS: float = 10.0
    ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP: bool = False
    ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL: bool = False
    ACCESS_CONTROL_OPENFGA_STORE_NAME: str = "agentarea"
    ACCESS_CONTROL_OPENFGA_MODEL_PATH: str | None = None
    # Bearer token sent with every request when the server runs with
    # OPENFGA_AUTHN_METHOD=preshared. Empty means the server accepts
    # unauthenticated requests (OPENFGA_AUTHN_METHOD=none, the OpenFGA default).
    ACCESS_CONTROL_OPENFGA_API_TOKEN: str = ""
