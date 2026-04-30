"""MCP server / instance DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the domain library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

INSTANCE_TRANSPORT_FIELDS = frozenset({"type", "endpoint_url", "image", "command", "args"})

# ---------------------------------------------------------------------------
# MCP server spec (a.k.a. "template") — catalog entry that an instance can
# reference via ``server_spec_id``.
# ---------------------------------------------------------------------------


class MCPServerCreate(BaseModel):
    """Payload for creating an MCP server spec (catalog template).

    Either ``docker_image_url`` (for container-based servers) or
    ``remote_url`` (for HTTP-based servers like GitHub Copilot) should be
    supplied. ``env_schema`` describes the variables an instance built from
    this spec needs to provide; secret entries (``isSecret: true``) are
    routed through the secret manager rather than stored in plaintext.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable MCP server name (unique per workspace).",
    )
    description: str = Field(
        description="Short summary of what this MCP server provides.",
    )
    docker_image_url: str | None = Field(
        default=None,
        description="Docker image URL for container-based MCP servers.",
    )
    remote_url: str | None = Field(
        default=None,
        description="Remote endpoint URL for HTTP-based MCP servers.",
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version of the MCP server spec.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags used for search and categorization.",
    )
    is_public: bool = Field(
        default=False,
        description="If true, the spec is visible across workspaces.",
    )
    env_schema: list[dict[str, Any]] | None = Field(
        default_factory=list,
        description=(
            "Environment-variable schema entries (KeyValueInput from the MCP "
            "registry). Each item has at least 'name' and 'description'; mark "
            "secrets with 'isSecret: true'."
        ),
    )
    cmd: list[str] | None = Field(
        default=None,
        description=(
            "Custom command override for container CMD (e.g. switching "
            "between stdio and HTTP modes)."
        ),
    )
    json_spec: dict[str, Any] | None = Field(
        default=None,
        description="Raw ServerJSON spec as published by the MCP registry.",
    )
    registry_url: str | None = Field(
        default=None,
        description="Source registry URL the spec was imported from.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v


class MCPServerUpdate(BaseModel):
    """Patch payload for an MCP server spec. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    docker_image_url: str | None = None
    remote_url: str | None = None
    version: str | None = None
    tags: list[str] | None = None
    is_public: bool | None = None
    status: str | None = Field(
        default=None,
        description="Lifecycle status of the spec (e.g. 'active', 'deprecated').",
    )
    env_schema: list[dict[str, Any]] | None = None
    cmd: list[str] | None = None
    json_spec: dict[str, Any] | None = None
    registry_url: str | None = None


# ---------------------------------------------------------------------------
# MCP server instance — a workspace-scoped, configured deployment of a spec.
# ---------------------------------------------------------------------------


class MCPServerInstanceCreate(BaseModel):
    """Payload for creating an MCP server instance.

    ``json_spec`` carries the connection configuration. Common shapes:

    - ``{"type": "url", "endpoint_url": "https://..."}``
    - ``{"type": "docker", "environment": {...}, "env_vars": [...]}``
    - ``{"type": "command", "command": [...], "environment": {...}}``
    For URL-type instances the service synchronously verifies the endpoint;
    docker/command kick off background verification.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Display name for this MCP server instance (unique per workspace).",
    )
    description: str | None = Field(
        default=None,
        description="Optional human-readable description of the instance.",
    )
    server_spec_id: str = Field(
        description=(
            "ID of an existing MCP server spec to derive defaults from "
            "(env_schema, secret routing, etc.)."
        ),
    )
    json_spec: dict[str, Any] = Field(
        description=(
            "Connection configuration. Must include 'type' "
            "('url' | 'docker' | 'command'); other keys depend on type."
        ),
    )
    auth_config_id: str | None = Field(
        default=None,
        description="ID of an MCP auth config (OAuth/credentials) to attach.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v

    @field_validator("server_spec_id")
    @classmethod
    def _strip_server_spec_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("server_spec_id is required")
        return v

    @model_validator(mode="after")
    def _reject_bundle_instances(self) -> MCPServerInstanceCreate:
        if (self.json_spec or {}).get("type") == "bundle":
            raise ValueError("bundle is not a valid MCP server instance type")
        return self


class MCPServerInstanceUpdate(BaseModel):
    """Patch payload for an MCP server instance. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    json_spec: dict[str, Any] | None = None

    @field_validator("json_spec")
    @classmethod
    def _reject_transport_field_updates(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        transport_fields = sorted(INSTANCE_TRANSPORT_FIELDS.intersection(v))
        if transport_fields:
            fields = ", ".join(transport_fields)
            raise ValueError(f"Instance json_spec cannot update transport fields: {fields}")
        return v
