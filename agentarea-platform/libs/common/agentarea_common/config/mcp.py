"""MCP (Model Context Protocol) configuration."""

from urllib.parse import urlparse
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings

MCP_MANAGER_AUTH_HEADER = "X-AgentArea-Manager-Authorization"

# Sandbox and MCP gateway keys that .env.example and docker-compose.dev.yaml once
# shipped. Anyone can sign with them, so a deployment still using one must rotate.
PUBLISHED_SECRET_VALUES = frozenset(
    {
        "dev-sandbox-activation-hmac-secret-change-in-prod",  # pragma: allowlist secret
        "dev-sandbox-cleanup-hmac-secret-change-in-prod-00",  # pragma: allowlist secret
        "dev-sandbox-file-auth-secret-change-in-prod-000000",  # pragma: allowlist secret
        "dev-sandbox-control-auth-secret-change-in-prod-0000",  # pragma: allowlist secret
        "dev-mcp-gateway-auth-secret-change-in-prod-00000000",  # pragma: allowlist secret
        "agentarea-dev-sandbox-activation-secret-change-me",  # pragma: allowlist secret
        "agentarea-dev-sandbox-cleanup-secret-change-me",  # pragma: allowlist secret
        "agentarea-dev-sandbox-file-secret-change-me",  # pragma: allowlist secret
        "agentarea-dev-sandbox-control-secret-change-me",  # pragma: allowlist secret
        "agentarea-dev-mcp-gateway-secret-change-me",  # pragma: allowlist secret
    }
)


def https_origin(url: str) -> str:
    """``scheme://host[:port]`` of an https URL; anything else is refused."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{url!r} is not an https URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_issuer(issuer: str) -> str:
    return issuer.strip().rstrip("/")


class MCPOAuthApp(BaseModel):
    """An OAuth app the operator registered with an authorization server without DCR.

    Every workspace connecting an MCP server at one of ``resource_origins``
    through ``issuer`` authorizes with it. Its endpoints, not discovery or a
    workspace's spec, are where the client secret is sent.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    issuer: str
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    authorization_endpoint: str
    token_endpoint: str
    resource_origins: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _refuse_loose_urls(self) -> "MCPOAuthApp":
        if not self.client_secret.get_secret_value():
            raise ValueError(f"MCP OAuth app for {self.issuer} has an empty client_secret")
        https_origin(self.issuer)
        if normalize_issuer(self.issuer) != self.issuer:
            raise ValueError(f"Issuer {self.issuer!r} must not end with a slash")
        https_origin(self.token_endpoint)
        https_origin(self.authorization_endpoint)
        for origin in self.resource_origins:
            if https_origin(origin) != origin:
                raise ValueError(f"Resource origin {origin!r} must be an exact https origin")
        return self


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration."""

    # Validation errors would otherwise echo AGENTAREA_MCP_OAUTH_APPS, secrets included.
    model_config = SettingsConfigDict(env_prefix="AGENTAREA_MCP_", hide_input_in_errors=True)

    MANAGER_URL: str = "http://mcp-manager:8000"
    GATEWAY_SECRET: SecretStr | None = None
    TIMEOUT: int = 30
    # Hydra advertises both the standard ``offline_access`` scope and its
    # legacy ``offline`` alias. OAuth clients such as Codex request the full
    # advertised set, so DCR clients must be registered for both or Hydra
    # rejects authorization with ``invalid_scope`` before login begins.
    OAUTH_SCOPES: str = "openid offline_access offline"
    # JSON list of MCPOAuthApp. Unset means no platform apps: providers without
    # DCR then need the workspace's own OAuth app.
    OAUTH_APPS: tuple[MCPOAuthApp, ...] = ()

    @field_validator("GATEWAY_SECRET")
    @classmethod
    def _reject_published_secret(
        cls, value: SecretStr | None, info: ValidationInfo
    ) -> SecretStr | None:
        if value is not None and value.get_secret_value() in PUBLISHED_SECRET_VALUES:
            raise ValueError(
                f"{info.field_name} is set to a value published in the AgentArea repository; "
                "generate a new one (scripts/gen-dev-secrets.sh rotates it) and restart"
            )
        return value

    @field_validator("OAUTH_APPS")
    @classmethod
    def _one_app_per_issuer(cls, apps: tuple[MCPOAuthApp, ...]) -> tuple[MCPOAuthApp, ...]:
        issuers = [app.issuer for app in apps]
        duplicates = sorted({issuer for issuer in issuers if issuers.count(issuer) > 1})
        if duplicates:
            raise ValueError(f"AGENTAREA_MCP_OAUTH_APPS lists {', '.join(duplicates)} twice")
        return apps

    def oauth_app_for(self, issuer: str) -> MCPOAuthApp | None:
        wanted = normalize_issuer(issuer)
        return next((app for app in self.OAUTH_APPS if app.issuer == wanted), None)

    def manager_gateway_url(self, instance_id: UUID | str) -> str:
        return f"{self.MANAGER_URL.rstrip('/')}/mcp/{instance_id}/mcp"

    def manager_retire_url(self, instance_id: UUID | str) -> str:
        return f"{self.MANAGER_URL.rstrip('/')}/mcp/{instance_id}"

    def manager_gateway_headers(self) -> dict[str, str]:
        if self.GATEWAY_SECRET is None:
            raise RuntimeError("AGENTAREA_MCP_GATEWAY_SECRET is required for container-backed MCP")
        secret = self.GATEWAY_SECRET.get_secret_value()
        if len(secret) < 32:
            raise RuntimeError("AGENTAREA_MCP_GATEWAY_SECRET must contain at least 32 bytes")
        return {MCP_MANAGER_AUTH_HEADER: f"Bearer {secret}"}

    def manager_inspection_headers(self) -> dict[str, str]:
        """Build the bearer header for internal manager inspection routes."""
        if self.GATEWAY_SECRET is None:
            raise RuntimeError("AGENTAREA_MCP_GATEWAY_SECRET is required for manager inspection")
        secret = self.GATEWAY_SECRET.get_secret_value()
        if len(secret) < 32:
            raise RuntimeError("AGENTAREA_MCP_GATEWAY_SECRET must contain at least 32 bytes")
        return {"Authorization": f"Bearer {secret}"}
