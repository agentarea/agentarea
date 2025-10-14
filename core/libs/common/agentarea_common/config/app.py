"""Application settings configuration."""

from functools import lru_cache

from .base import BaseAppSettings


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False

    # Kratos Authentication Configuration
    KRATOS_JWKS_B64: str = "ewogICJrZXlzIjogWwogICAgewogICAgICAia3R5IjogIkVDIiwKICAgICAgImtpZCI6ICJhZ2VudGFyZWEtand0LWtleS0xIiwKICAgICAgInVzZSI6ICJzaWciLAogICAgICAiYWxnIjogIkVTMjU2IiwKICAgICAgImNydiI6ICJQLTI1NiIsCiAgICAgICJ4IjogIk1LQkNUTkljS1VTRGlpMTF5U3MzNTI2aURaOEFpVG83VHU2S1BBcXY3RDQiLAogICAgICAieSI6ICI0RXRsNlNSVzJZaUxVck41dmZ2Vkh1aHA3eDhQeGx0bVdXbGJiTTRJRnlNIiwKICAgICAgImQiOiAiODcwTUI2Z2Z1VEo0SHRVblV2WU15SnByNWVVWk5QNEJrNDNiVmRqM2VBRSIKICAgIH0KICBdCn0="  # noqa: E501
    KRATOS_ISSUER: str = "https://agentarea.dev"
    KRATOS_AUDIENCE: str = "agentarea-api"


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings()
