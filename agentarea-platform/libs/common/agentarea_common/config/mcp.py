"""MCP (Model Context Protocol) configuration."""

from uuid import UUID

from pydantic import SecretStr, ValidationInfo, field_validator
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


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration."""

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_MCP_")

    MANAGER_URL: str = "http://mcp-manager:8000"
    GATEWAY_SECRET: SecretStr | None = None
    TIMEOUT: int = 30
    # Hydra advertises both the standard ``offline_access`` scope and its
    # legacy ``offline`` alias. OAuth clients such as Codex request the full
    # advertised set, so DCR clients must be registered for both or Hydra
    # rejects authorization with ``invalid_scope`` before login begins.
    OAUTH_SCOPES: str = "openid offline_access offline"

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
