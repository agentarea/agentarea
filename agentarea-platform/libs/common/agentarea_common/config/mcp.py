"""MCP (Model Context Protocol) configuration."""

from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import SettingsConfigDict

from .base import BaseAppSettings

MCP_MANAGER_AUTH_HEADER = "X-AgentArea-Manager-Authorization"


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration.

    Sandbox and Hydra fields live here because the MCP paths consume them, but
    they belong to the sandbox and auth domains and carry those env names via
    an explicit alias rather than being filed under ``AGENTAREA_MCP_``.
    """

    model_config = SettingsConfigDict(env_prefix="AGENTAREA_MCP_")

    MANAGER_URL: str = "http://mcp-manager:8000"
    GATEWAY_SECRET: SecretStr | None = None
    TIMEOUT: int = 30
    # Hydra advertises both the standard ``offline_access`` scope and its
    # legacy ``offline`` alias. OAuth clients such as Codex request the full
    # advertised set, so DCR clients must be registered for both or Hydra
    # rejects authorization with ``invalid_scope`` before login begins.
    OAUTH_SCOPES: str = "openid offline_access offline"
    # Allow OpenAPI connections to reach localhost/private IPs (self-hosted deployments)
    ALLOW_PRIVATE_URLS: bool = False

    SBX_INSPECT_SECRET: SecretStr | None = Field(
        default=None, validation_alias="AGENTAREA_SBX_INSPECT_SECRET"
    )
    SBX_FILE_SECRET: SecretStr | None = Field(
        default=None, validation_alias="AGENTAREA_SBX_FILE_SECRET"
    )
    SBX_CONTROL_SECRET: SecretStr | None = Field(
        default=None, validation_alias="AGENTAREA_SBX_CONTROL_SECRET"
    )

    HYDRA_URL: str = Field(default="http://hydra:4444", validation_alias="AGENTAREA_AUTH_HYDRA_URL")
    HYDRA_ADMIN_URL: str = Field(
        default="http://hydra:4445", validation_alias="AGENTAREA_AUTH_HYDRA_ADMIN_URL"
    )
    HYDRA_BROWSER_URL: str = Field(
        default="http://localhost:4444", validation_alias="AGENTAREA_AUTH_HYDRA_BROWSER_URL"
    )
    # Expected audience for Hydra-issued OAuth tokens. When set, the API
    # enforces the `aud` claim (rejecting tokens minted for other clients).
    # Required to accept Hydra-issued tokens at all. Unset does NOT mean
    # "verify without an audience" any more — it means Hydra bearer tokens are
    # refused outright, so a deployment that does not run Hydra is unaffected
    # while one that does must declare which audience it accepts.
    HYDRA_AUDIENCE: str | None = Field(
        default=None, validation_alias="AGENTAREA_AUTH_HYDRA_AUDIENCE"
    )

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
