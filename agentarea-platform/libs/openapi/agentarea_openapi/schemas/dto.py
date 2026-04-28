"""OpenAPI connection CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the domain library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_url_field(v: str | None) -> str | None:
    """SSRF guard for URL fields. Imported lazily to avoid app-config coupling."""
    if v is None:
        return v
    from agentarea_common.config import get_settings

    from agentarea_openapi.application.url_validator import validate_url

    try:
        validate_url(v, allow_private=get_settings().mcp.ALLOW_PRIVATE_URLS)
    except ValueError as e:
        raise ValueError(str(e)) from e
    return v


class HeaderInput(BaseModel):
    """One custom HTTP header attached to an OpenAPI connection.

    Non-safe header names (e.g. ``Authorization``) are stored encrypted in the
    secret manager — pass the plaintext value here at create/update time.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        max_length=256,
        description="HTTP header name. Allowed characters: letters, digits, '-', '_'.",
    )
    value: str = Field(
        default="",
        max_length=8192,
        description="Header value. May not contain CR, LF, or NUL bytes.",
    )

    @field_validator("name")
    @classmethod
    def _validate_header_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9\-_]+$", v.strip()):
            raise ValueError("Header name contains invalid characters")
        return v.strip()

    @field_validator("value")
    @classmethod
    def _validate_header_value(cls, v: str) -> str:
        if "\r" in v or "\n" in v or "\x00" in v:
            raise ValueError("Header value contains invalid characters")
        return v


class HeaderOutput(BaseModel):
    """Header metadata returned in API responses (secret values are masked)."""

    name: str
    secret: bool
    value: str | None = None


class OpenAPIConnectionCreate(BaseModel):
    """Payload for creating an OpenAPI connection.

    The connection ties a base URL (where requests are sent) to an
    OpenAPI 3.x specification (which is parsed eagerly into a tool list).
    Provide either ``spec_url`` or ``spec_content`` — not both required.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Display name for the connection (unique per workspace).",
    )
    base_url: str = Field(
        max_length=500,
        description="Base URL for API requests, e.g. 'https://api.example.com'.",
    )
    description: str | None = Field(
        default=None,
        description="Optional human-readable summary of what this API exposes.",
    )
    spec_url: str | None = Field(
        default=None,
        description=(
            "URL to an OpenAPI 3.x JSON or YAML spec. The spec is fetched and "
            "parsed eagerly at create time so the connection is ready for use."
        ),
    )
    spec_content: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Inline OpenAPI 3.x spec as a JSON object. Use instead of "
            "``spec_url`` when the spec host is unreachable from the API."
        ),
    )
    auth_config_id: UUID | None = Field(
        default=None,
        description=(
            "Optional MCPAuthConfig UUID for OAuth2 token rotation. "
            "When set, tokens are minted/refreshed on the connection's behalf."
        ),
    )
    custom_headers: list[HeaderInput] | None = Field(
        default=None,
        description=(
            "Custom HTTP headers attached to every request. Non-safe headers "
            "(e.g. Authorization) are stored encrypted in the secret manager."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        return _validate_url_field(v)  # type: ignore[return-value]

    @field_validator("spec_url")
    @classmethod
    def _validate_spec_url(cls, v: str | None) -> str | None:
        return _validate_url_field(v)


class OpenAPIConnectionUpdate(BaseModel):
    """Patch payload for an OpenAPI connection. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    base_url: str | None = Field(default=None, max_length=500)
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None
    auth_config_id: UUID | None = Field(
        default=None,
        description="Optional MCPAuthConfig UUID for OAuth2 token rotation.",
    )
    custom_headers: list[HeaderInput] | None = Field(
        default=None,
        description=(
            "Replace the full custom-header set. Pass [] to clear all. Secret "
            "values are stored encrypted in the secret manager."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str | None) -> str | None:
        return _validate_url_field(v)

    @field_validator("spec_url")
    @classmethod
    def _validate_spec_url(cls, v: str | None) -> str | None:
        return _validate_url_field(v)
