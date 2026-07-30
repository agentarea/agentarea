"""MCP (Model Context Protocol) configuration."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings

from .base import BaseAppSettings


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration."""

    MCP_MANAGER_URL: str = "http://mcp-manager:8000"
    SANDBOX_CLEANUP_AUTH_SECRET: SecretStr | None = None
    SANDBOX_INSPECTION_AUTH_SECRET: SecretStr | None = None
    MCP_GATEWAY_URL: str = "http://agentarea-traefik:8080"
    MCP_CLIENT_TIMEOUT: int = 30
    REDIS_URL: str = "redis://localhost:6379"
    HYDRA_PUBLIC_URL: str = "http://hydra:4444"
    HYDRA_ADMIN_URL: str = "http://hydra:4445"
    HYDRA_BROWSER_URL: str = "http://localhost:4444"
    # Expected audience for Hydra-issued OAuth tokens. When set, the API
    # enforces the `aud` claim (rejecting tokens minted for other clients).
    # Unset = audience not verified (back-compat); set to this API's resource
    # identifier to harden the MCP OAuth path.
    HYDRA_AUDIENCE: str | None = None
    MCP_OAUTH_SCOPES: str = "openid offline_access"
    # Allow OpenAPI connections to reach localhost/private IPs (self-hosted deployments)
    ALLOW_PRIVATE_URLS: bool = False


class MCPManagerSettings(BaseSettings):
    """MCP Manager service configuration."""

    base_url: str = "http://localhost:8001"
    api_key: str | None = None
    timeout: int = 30
    max_retries: int = 3

    class Config:
        """Configuration for MCPManagerSettings."""

        env_prefix = "MCP_MANAGER_"
