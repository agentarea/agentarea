"""Application settings configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings

A2A_AGENT_ID_PLACEHOLDER = "{agent_id}"


class AppSettings(BaseAppSettings):
    """General application configuration."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_")

    APP_NAME: str = "AI Agent Service"
    DEBUG: bool = False
    EDITION: str = "oss"

    # Max accepted request body size (bytes). Rejects oversized payloads with
    # 413 before they are buffered. Generous default so file uploads / workspace
    # imports keep working; tighten per deployment if needed.
    API_MAX_BODY: int = 50 * 1024 * 1024  # 50 MB

    # Multipart task attachments are bounded independently so the API can
    # reject the whole upload before workflow dispatch while leaving room for
    # multipart framing under AGENTAREA_API_MAX_BODY.
    TASK_ATTACH_MAX_FILES: int = 100
    TASK_ATTACH_MAX_SIZE: int = 40 * 1024 * 1024
    TASK_ATTACH_MAX_TOTAL: int = 45 * 1024 * 1024
    # What runs a task: a Temporal workflow, or the agent loop inside the API
    # process (no durability; local development only).
    TASK_EXECUTOR: Literal["temporal", "direct"] = "temporal"

    # Public base URL for this API (used in OAuth AS metadata and redirect URLs)
    API_URL: str = "http://localhost:8000"
    # Public base URL Telegram should POST bot webhooks to, as
    # {base}/webhooks/{webhook_id}. Usually the same host as the API; in a
    # deployment where Telegram cannot reach that host directly (e.g. behind a
    # relay), point this at the reachable ingress instead. Empty = fall back to
    # AGENTAREA_API_URL.
    TELEGRAM_WEBHOOK_URL: str = ""
    # AgentArea frontend URL (users are redirected here to log in if no session)
    APP_URL: str = "http://localhost:3000"
    # Where each agent is served over A2A. One host per agent, so its card sits
    # at /.well-known/agent-card.json on its own origin (RFC 8615); the first
    # label of the host is the agent id. Needs a wildcard DNS record and
    # certificate for the zone, e.g. https://{agent_id}.a2a.example.com.
    A2A_AGENT_URL: str = "http://{agent_id}.a2a.localhost:8000"

    # Optional SearXNG-compatible endpoint used by agentarea/web.search_web.
    # When unset, search attempts fail explicitly; URL fetching remains usable.
    TOOL_SEARCH_URL: str | None = None

    # Comma-separated browser origins allowed to make credentialed CORS requests.
    # Defaults to the local frontend. NEVER "*": with allow_credentials=True a
    # wildcard reflects any origin for credentialed reads. In prod set e.g.:
    #   AGENTAREA_CORS_ORIGINS=https://app.agentarea.dev,https://admin.agentarea.dev
    CORS_ORIGINS: str = "http://localhost:3000"

    # Optional regex matching additional allowed origins — for preview/staging
    # subdomains that can't be enumerated (e.g. r"https://.*\.agentarea\.dev",
    # Vercel previews r"https://.*-myorg\.vercel\.app"). Unset = static list only.
    CORS_ORIGIN_REGEX: str | None = None

    # Remaining CORS knobs, all overridable for self-hosted/enterprise needs.
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: str = "*"  # comma-separated, or "*"
    CORS_HEADERS: str = "*"  # comma-separated, or "*"
    CORS_MAX_AGE: int = 3600  # preflight cache seconds

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Parsed list of allowed CORS origins (comma-separated, blanks dropped)."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def cors_allowed_methods(self) -> list[str]:
        """Parsed list of allowed CORS methods (comma-separated, blanks dropped)."""
        return [m.strip() for m in self.CORS_METHODS.split(",") if m.strip()]

    @property
    def cors_allowed_headers(self) -> list[str]:
        """Parsed list of allowed CORS request headers (comma-separated)."""
        return [h.strip() for h in self.CORS_HEADERS.split(",") if h.strip()]

    @model_validator(mode="after")
    def _reject_wildcard_origin_with_credentials(self) -> "AppSettings":
        """Fail fast on the one CORS combo that is always a CSRF hole.

        ``allow_origins=["*"]`` together with ``allow_credentials=True`` makes
        the gateway reflect any origin for credentialed reads. The CORS spec
        forbids it; Starlette silently reflects instead. Operators who really
        want a wildcard must disable credentials.
        """
        if self.CORS_CREDENTIALS and "*" in self.cors_allowed_origins:
            raise ValueError(
                "CORS misconfiguration: AGENTAREA_CORS_ORIGINS='*' with "
                "AGENTAREA_CORS_CREDENTIALS=true reflects any origin for credentialed "
                "requests (CSRF risk). Set explicit origins (or a regex), or set "
                "CORS_CREDENTIALS=false."
            )
        return self

    @model_validator(mode="after")
    def _check_a2a_agent_url(self) -> "AppSettings":
        """Refuse an A2A address the agent cannot be found by."""
        parsed = urlsplit(self.A2A_AGENT_URL)
        hostname = parsed.hostname or ""
        if (
            parsed.scheme not in ("http", "https")
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not hostname.startswith(f"{A2A_AGENT_ID_PLACEHOLDER}.")
            or self.A2A_AGENT_URL.count(A2A_AGENT_ID_PLACEHOLDER) != 1
        ):
            raise ValueError(
                f"AGENTAREA_A2A_AGENT_URL must be an http(s) origin whose host starts with "
                f"'{A2A_AGENT_ID_PLACEHOLDER}.', e.g. https://{A2A_AGENT_ID_PLACEHOLDER}"
                f".a2a.example.com; got {self.A2A_AGENT_URL!r}"
            )
        return self

    @property
    def a2a_agent_host(self) -> str:
        """The host pattern agents are served on, e.g. ``{agent_id}.a2a.example.com``."""
        return urlsplit(self.A2A_AGENT_URL).hostname or ""

    def a2a_agent_url(self, agent_id: object) -> str:
        """The A2A address of one agent: its origin, where its card is discovered."""
        return self.A2A_AGENT_URL.rstrip("/").replace(A2A_AGENT_ID_PLACEHOLDER, str(agent_id))

    # Kratos public API URL (used to validate browser session cookies in OAuth AS)
    AUTH_KRATOS_URL: str = "http://kratos:4433"

    # Runtime environment (development / staging / production)
    ENV: str = "development"

    # Explicit hostname for reaching services on the host machine from within a container.
    # If unset, auto-detected: host.docker.internal inside Docker, localhost otherwise.
    LOCAL_HOST: str | None = None

    @property
    def local_host(self) -> str:
        """Hostname for reaching services running on the host machine.

        Returns 'host.docker.internal' when running inside a Docker container,
        'localhost' otherwise. Works for any local inference engine
        (Ollama, vLLM, LM Studio, llama.cpp, etc.).

        Override via AGENTAREA_LOCAL_HOST env var.
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
