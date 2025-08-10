"""MCP (Model Context Protocol) configuration."""

from pydantic_settings import BaseSettings

from .base import BaseAppSettings


class MCPSettings(BaseAppSettings):
    """MCP (Model Context Protocol) configuration."""

    MCP_MANAGER_URL: str = "http://mcp-manager:8000"  # Internal container communication
    MCP_PROXY_HOST: str = "http://localhost:7999"  # Host for agents to access MCP servers
    MCP_CLIENT_TIMEOUT: int = 30
    REDIS_URL: str = "redis://localhost:6379"


class MCPManagerSettings(BaseSettings):
    """MCP Manager service configuration."""

    base_url: str = "http://localhost:8001"
    api_key: str | None = None
    timeout: int = 30
    max_retries: int = 3

    class Config:
        """Configuration for MCPManagerSettings."""

        env_prefix = "MCP_MANAGER_"
