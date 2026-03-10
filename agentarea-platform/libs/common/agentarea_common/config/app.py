"""Application settings configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False

    # Public base URL for this API (used in OAuth AS metadata and redirect URLs)
    API_BASE_URL: str = "http://localhost:8000"
    # AgentArea frontend URL (users are redirected here to log in if no session)
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # Kratos public API URL (used to validate browser session cookies in OAuth AS)
    KRATOS_PUBLIC_URL: str = "http://kratos:4433"

    # Kratos Authentication Configuration
    KRATOS_JWKS_B64: str = (
        "ewogICJrZXlzIjogWwogICAgewogICAgICAia3R5IjogIkVDIiwKICAgICAgImtpZCI6ICJh"
        "Z2VudGFyZWEtand0LWtleS0xIiwKICAgICAgInVzZSI6ICJzaWciLAogICAgICAiYWxnIjo"
        "gIkVTMjU2IiwKICAgICAgImNydiI6ICJQLTI1NiIsCiAgICAgICJ4IjogIk1LQkNUTkljS1"
        "VTRGlpMTF5U3MzNTI2aURaOEFpVG83VHU2S1BBcXY3RDQiLAogICAgICAieSI6ICI0RXRs"
        "NlNSVzJZaUxVck41dmZ2Vkh1aHA3eDhQeGx0bVdXbGJiTTRJRnlNIiwKICAgICAgImQiOiA"
        "iODcwTUI2Z2Z1VEo0SHRVblV2WU15SnByNWVVWk5QNEJrNDNiVmRqM2VBRSIKICAgIH0KIC"
        "BdCn0="
    )
    KRATOS_ISSUER: str = "https://agentarea.dev"
    KRATOS_AUDIENCE: str = "agentarea-api"


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings()
