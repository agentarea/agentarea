"""Provider-config CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the domain library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderConfigCreate(BaseModel):
    """Payload for creating an LLM provider configuration."""

    model_config = ConfigDict(extra="forbid")

    provider_spec_id: UUID = Field(
        description=(
            "UUID of the provider specification (e.g. OpenAI, Anthropic) "
            "this configuration targets. Look up via list_specs."
        ),
    )
    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable label for this provider configuration.",
    )
    api_key: str | None = Field(
        default=None,
        description=(
            "Secret API key for the provider. Stored encrypted in the "
            "secret manager; never returned in responses. May be empty "
            "for proxies that accept keyless traffic — the backend "
            "suppresses the Authorization header when this is empty."
        ),
    )
    endpoint_url: str | None = Field(
        default=None,
        description=(
            "Optional custom endpoint URL (e.g. for self-hosted or proxied "
            "providers). Leave unset to use the provider's default."
        ),
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional human-readable description of this configuration.",
    )
    is_public: bool = Field(
        default=False,
        description=(
            "If True, the configuration is visible to all workspace members; "
            "otherwise it is scoped to the creator."
        ),
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v

    @field_validator("api_key", mode="before")
    @classmethod
    def _normalize_api_key(cls, v: object) -> object:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped or None
        return v


class ProviderConfigUpdate(BaseModel):
    """Patch payload for an existing provider configuration. Unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New human-readable label for the configuration.",
    )
    api_key: str | None = Field(
        default=None,
        description=(
            "New API key. Replaces the previously stored secret. Send an empty "
            "string to clear the key for keyless custom endpoints."
        ),
    )
    endpoint_url: str | None = Field(
        default=None,
        description="New endpoint URL, or empty string to clear.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="New description for the configuration.",
    )
    is_active: bool | None = Field(
        default=None,
        description="Activate or deactivate the configuration.",
    )
    is_public: bool | None = Field(
        default=None,
        description="Toggle workspace-wide visibility.",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def _normalize_api_key(cls, v: object) -> object:
        if isinstance(v, str):
            stripped = v.strip()
            return stripped or None
        return v
