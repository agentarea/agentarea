"""Pydantic schemas for agent import/export YAML configuration."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SkillYAML(BaseModel):
    """Skill configuration in YAML format.

    Supports multiple source types:
    - content: Raw markdown content inline
    - github: GitHub repository URL
    - path: Local file/directory path (relative to YAML file)
    """

    name: str | None = Field(
        default=None,
        description="Skill name. If not provided, parsed from SKILL.md frontmatter.",
    )
    description: str | None = Field(
        default=None,
        description="Skill description. If not provided, parsed from SKILL.md frontmatter.",
    )
    # Source options - exactly one must be provided
    content: str | None = Field(
        default=None,
        description="Raw markdown content for single-file skills.",
    )
    github: str | None = Field(
        default=None,
        description="GitHub repository URL (e.g., https://github.com/owner/repo).",
    )
    path: str | None = Field(
        default=None,
        description="Local path to skill file, directory, or archive (relative to YAML file).",
    )

    @model_validator(mode="after")
    def validate_source(self) -> "SkillYAML":
        """Ensure exactly one source is provided."""
        sources = [self.content, self.github, self.path]
        provided = [s for s in sources if s is not None]
        if len(provided) == 0:
            raise ValueError("Skill must have one source: 'content', 'github', or 'path'")
        if len(provided) > 1:
            raise ValueError("Skill can only have one source: 'content', 'github', or 'path'")
        return self


class ToolSettingsYAML(BaseModel):
    """Tool settings configuration in YAML format."""

    disabled_methods: list[str] | None = None  # For code tools
    # FIXME: should be a proper typed model (e.g. MCPToolPermission) instead of Any
    allowed_tools: list[Any] | None = (
        None  # str (legacy) or {tool_name, requires_user_confirmation}
    )
    a2a_url: str | None = None  # For agent tools — explicit A2A endpoint URL
    description_override: str | None = None  # For agent tools — custom description
    requires_user_confirmation: bool | None = None  # Require human approval before execution


class ToolConfigYAML(BaseModel):
    """Tool configuration in YAML format."""

    type: Literal["code", "mcp", "agent"]
    name: str
    settings: ToolSettingsYAML | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate that tool name is not empty."""
        if not v or not v.strip():
            raise ValueError("Tool name cannot be empty")
        return v.strip()


class AgentYAML(BaseModel):
    """Agent configuration in YAML format (without model_id)."""

    id: str | None = Field(
        default=None,
        description="Optional agent ID (UUID). If not provided, a new UUID will be generated.",
    )
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=1000)
    instruction: str = Field(default="", max_length=5000)
    tools: list[ToolConfigYAML] | None = None
    planning: bool | None = False
    a2ui_enabled: bool | None = False
    agent_type: str = Field(
        default="stateless",
        description="Agent type: 'stateful' (maintains conversation context) or 'stateless' (each request independent).",
    )
    skill_names: list[str] | None = Field(
        default=None,
        description="List of skill names to attach. Skills must be defined in the same YAML or already exist.",
    )

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

    skills: list[SkillYAML] = Field(default_factory=list)
    agents: list[AgentYAML] = Field(default_factory=list)
    mcp_instances: list[MCPInstanceYAML] = Field(default_factory=list)
    provider_configs: list[ProviderConfigYAML] = Field(default_factory=list)

    @field_validator("skills", "agents", "mcp_instances", "provider_configs", mode="before")
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
    created_skills: int = 0
    created_agents: int = 0
    created_mcp_instances: int = 0
    created_provider_configs: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
