"""Application settings configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator

from .base import BaseAppSettings


class AppSettings(BaseAppSettings):
    """General application configuration."""

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False
    DEPLOYMENT_MODE: str = "oss"

    # Max accepted request body size (bytes). Rejects oversized payloads with
    # 413 before they are buffered. Generous default so file uploads / workspace
    # imports keep working; tighten per deployment if needed.
    MAX_REQUEST_BODY_BYTES: int = 50 * 1024 * 1024  # 50 MB

    # Shared secret for internal service-to-service calls (e.g. the Go event
    # service calling the public trigger-execute endpoint). When set, those
    # endpoints require a matching X-Internal-Token header. Unset = not enforced.
    INTERNAL_API_TOKEN: str | None = None

    # Public base URL for this API (used in OAuth AS metadata and redirect URLs)
    API_BASE_URL: str = "http://localhost:8000"
    # AgentArea frontend URL (users are redirected here to log in if no session)
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # Comma-separated browser origins allowed to make credentialed CORS requests.
    # Defaults to the local frontend. NEVER "*": with allow_credentials=True a
    # wildcard reflects any origin for credentialed reads. In prod set e.g.:
    #   CORS_ALLOWED_ORIGINS=https://app.agentarea.dev,https://admin.agentarea.dev
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Optional regex matching additional allowed origins — for preview/staging
    # subdomains that can't be enumerated (e.g. r"https://.*\.agentarea\.dev",
    # Vercel previews r"https://.*-myorg\.vercel\.app"). Unset = static list only.
    CORS_ALLOWED_ORIGIN_REGEX: str | None = None

    # Remaining CORS knobs, all overridable for self-hosted/enterprise needs.
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOWED_METHODS: str = "*"  # comma-separated, or "*"
    CORS_ALLOWED_HEADERS: str = "*"  # comma-separated, or "*"
    CORS_MAX_AGE: int = 3600  # preflight cache seconds

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Parsed list of allowed CORS origins (comma-separated, blanks dropped)."""
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def cors_allowed_methods(self) -> list[str]:
        """Parsed list of allowed CORS methods (comma-separated, blanks dropped)."""
        return [m.strip() for m in self.CORS_ALLOWED_METHODS.split(",") if m.strip()]

    @property
    def cors_allowed_headers(self) -> list[str]:
        """Parsed list of allowed CORS request headers (comma-separated)."""
        return [h.strip() for h in self.CORS_ALLOWED_HEADERS.split(",") if h.strip()]

    @model_validator(mode="after")
    def _reject_wildcard_origin_with_credentials(self) -> "AppSettings":
        """Fail fast on the one CORS combo that is always a CSRF hole.

        ``allow_origins=["*"]`` together with ``allow_credentials=True`` makes
        the gateway reflect any origin for credentialed reads. The CORS spec
        forbids it; Starlette silently reflects instead. Operators who really
        want a wildcard must disable credentials.
        """
        if self.CORS_ALLOW_CREDENTIALS and "*" in self.cors_allowed_origins:
            raise ValueError(
                "CORS misconfiguration: CORS_ALLOWED_ORIGINS='*' with "
                "CORS_ALLOW_CREDENTIALS=true reflects any origin for credentialed "
                "requests (CSRF risk). Set explicit origins (or a regex), or set "
                "CORS_ALLOW_CREDENTIALS=false."
            )
        return self

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

    # Ollama endpoint override. Named after litellm's native env var so one
    # setting covers both our code and litellm's own resolution.
    OLLAMA_API_BASE: str | None = None

    @property
    def ollama_api_base(self) -> str:
        """Base URL for a local Ollama instance.

        OLLAMA_API_BASE env wins; otherwise built from local_host so it
        resolves correctly both inside Docker and on the host.
        """
        return self.OLLAMA_API_BASE or f"http://{self.local_host}:11434"


@lru_cache
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return AppSettings()
