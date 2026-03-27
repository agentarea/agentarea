"""Application settings configuration."""

from functools import lru_cache
from pathlib import Path

from .base import BaseAppSettings


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False
    DEPLOYMENT_MODE: str = "oss"

    # Public base URL for this API (used in OAuth AS metadata and redirect URLs)
    API_BASE_URL: str = "http://localhost:8000"
    # AgentArea frontend URL (users are redirected here to log in if no session)
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # Kratos public API URL (used to validate browser session cookies in OAuth AS)
    KRATOS_PUBLIC_URL: str = "http://kratos:4433"

    # Runtime environment (development / staging / production)
    ENVIRONMENT: str = "development"

    # Explicit hostname for reaching services on the host machine from within a container.
    # If unset, auto-detected: host.docker.internal inside Docker, localhost otherwise.
    LOCAL_HOST: str | None = None

    @property
    def local_host(self) -> str:
        """Hostname for reaching services running on the host machine.

        Returns 'host.docker.internal' when running inside a Docker container,
        'localhost' otherwise. Works for any local inference engine
        (Ollama, vLLM, LM Studio, llama.cpp, etc.).

        Override via LOCAL_HOST env var.
        On Linux Docker Engine (no Docker Desktop), add to compose.yaml:
            extra_hosts: ["host.docker.internal:host-gateway"]
        """
        if self.LOCAL_HOST:
            return self.LOCAL_HOST
        # Explicit opt-in via Dockerfile ENV (most reliable, works everywhere)
        if Path("/.dockerenv").exists():
            return "host.docker.internal"
        return "localhost"


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings()
