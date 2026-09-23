"""MCP (Model Context Protocol) configuration."""

from uuid import UUID

from pydantic import SecretStr
from pydantic_settings import BaseSettings

from .base import BaseAppSettings

MCP_MANAGER_AUTH_HEADER = "X-AgentArea-Manager-Authorization"


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration."""

    MCP_MANAGER_URL: str = "http://mcp-manager:8000"
    MCP_GATEWAY_AUTH_SECRET: SecretStr | None = None
    SANDBOX_INSPECTION_AUTH_SECRET: SecretStr | None = None
    SANDBOX_FILE_AUTH_SECRET: SecretStr | None = None
    SANDBOX_CONTROL_AUTH_SECRET: SecretStr | None = None
    MCP_CLIENT_TIMEOUT: int = 30
    REDIS_URL: str = "redis://localhost:6379"
    HYDRA_PUBLIC_URL: str = "http://hydra:4444"
    HYDRA_ADMIN_URL: str = "http://hydra:4445"
    HYDRA_BROWSER_URL: str = "http://localhost:4444"
    # Expected audience for Hydra-issued OAuth tokens. When set, the API
    # enforces the `aud` claim (rejecting tokens minted for other clients).
    # Required to accept Hydra-issued tokens at all. Unset does NOT mean
    # "verify without an audience" any more — it means Hydra bearer tokens are
    # refused outright, so a deployment that does not run Hydra is unaffected
    # while one that does must declare which audience it accepts.
    HYDRA_AUDIENCE: str | None = None
    # Hydra advertises both the standard ``offline_access`` scope and its
    # legacy ``offline`` alias. OAuth clients such as Codex request the full
    # advertised set, so DCR clients must be registered for both or Hydra
    # rejects authorization with ``invalid_scope`` before login begins.
    MCP_OAUTH_SCOPES: str = "openid offline_access offline"
    # Allow OpenAPI connections to reach localhost/private IPs (self-hosted deployments)
    ALLOW_PRIVATE_URLS: bool = False

    def manager_gateway_url(self, instance_id: UUID | str) -> str:
        return f"{self.MCP_MANAGER_URL.rstrip('/')}/mcp/{instance_id}/mcp"

    def manager_retire_url(self, instance_id: UUID | str) -> str:
        return f"{self.MCP_MANAGER_URL.rstrip('/')}/mcp/{instance_id}"

    def manager_gateway_headers(self) -> dict[str, str]:
        if self.MCP_GATEWAY_AUTH_SECRET is None:
            raise RuntimeError("MCP_GATEWAY_AUTH_SECRET is required for container-backed MCP")
        secret = self.MCP_GATEWAY_AUTH_SECRET.get_secret_value()
        if len(secret) < 32:
            raise RuntimeError("MCP_GATEWAY_AUTH_SECRET must contain at least 32 bytes")
        return {MCP_MANAGER_AUTH_HEADER: f"Bearer {secret}"}


class MCPManagerSettings(BaseSettings):
    """MCP Manager service configuration."""

    base_url: str = "http://localhost:8001"
    api_key: str | None = None
    timeout: int = 30
    max_retries: int = 3

    class Config:
        """Configuration for MCPManagerSettings."""

        env_prefix = "MCP_MANAGER_"
