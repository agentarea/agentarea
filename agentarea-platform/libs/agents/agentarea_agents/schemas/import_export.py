"""Pydantic schemas for agent import/export YAML configuration."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class BuiltinToolConfigYAML(BaseModel):
    """Builtin tool configuration in YAML format."""

    tool_name: str
    enabled: bool = True
    requires_user_confirmation: bool = False

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        """Validate that tool name is not empty."""
        if not v or not v.strip():
            raise ValueError("tool_name cannot be empty")
        return v.strip()


class MCPToolConfigYAML(BaseModel):
    """MCP tool configuration in YAML format."""

    tool_name: str
    requires_user_confirmation: bool = False


class MCPServerConfigYAML(BaseModel):
    """MCP server configuration in YAML format."""

    mcp_server_id: str  # Reference to server spec ID
    allowed_tools: list[MCPToolConfigYAML] | None = None


class ToolsConfigYAML(BaseModel):
    """Complete tools configuration in YAML format."""

    builtin_tools: list[BuiltinToolConfigYAML] | None = None
    mcp_server_configs: list[MCPServerConfigYAML] | None = None
    planning: bool | None = False


class AgentYAML(BaseModel):
    """Agent configuration in YAML format (without model_id)."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    instruction: str = Field(default="", max_length=5000)
    tools_config: ToolsConfigYAML | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate agent name is not just whitespace."""
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty or whitespace")
        return v.strip()


class MCPInstanceYAML(BaseModel):
    """MCP server instance configuration in YAML format."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    server_spec_id: str  # Reference to MCP server spec
    env_vars: dict[str, str] = Field(default_factory=dict)  # Secrets as placeholders

    @field_validator("env_vars")
    @classmethod
    def validate_env_vars(cls, v: dict[str, str]) -> dict[str, str]:
        """Ensure env_vars is a dict with string keys and values."""
        if not isinstance(v, dict):
            raise ValueError("env_vars must be a dictionary")
        for key, value in v.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("env_vars keys and values must be strings")
        return v


class ProviderConfigYAML(BaseModel):
    """Provider configuration in YAML format (without secrets)."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    provider_spec_id: str  # Reference to provider spec
    endpoint_url: str | None = None
    api_key_placeholder: str = Field(
        default="<REQUIRED>",
        description="Placeholder for API key - must be replaced on import",
    )

    @field_validator("api_key_placeholder")
    @classmethod
    def validate_api_key_placeholder(cls, v: str) -> str:
        """Ensure placeholder is present."""
        if not v or v.strip() == "":
            return "<REQUIRED>"
        return v


class WorkspaceConfigYAML(BaseModel):
    """Complete workspace configuration in YAML format."""

    agents: list[AgentYAML] = Field(default_factory=list)
    mcp_instances: list[MCPInstanceYAML] = Field(default_factory=list)
    provider_configs: list[ProviderConfigYAML] = Field(default_factory=list)

    @field_validator("agents", "mcp_instances", "provider_configs", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> list:
        """Ensure fields are lists even if None."""
        return v if v is not None else []


class ImportOptions(BaseModel):
    """Options for import operation."""

    skip_missing_dependencies: bool = Field(
        default=False,
        description="Skip resources with missing dependencies instead of failing",
    )
    override_existing: bool = Field(
        default=False, description="Override existing resources with same name"
    )


class ImportResult(BaseModel):
    """Result of an import operation."""

    success: bool
    created_agents: int = 0
    created_mcp_instances: int = 0
    created_provider_configs: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
