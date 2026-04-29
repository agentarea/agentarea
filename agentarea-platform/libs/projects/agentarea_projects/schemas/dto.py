"""Project CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

These models live in the domain library (not the API app) so the toolset
in ``apps/api/agentarea_api/tools`` and the service in this lib can both
import them without layering inversion. Field descriptions are written for
LLM consumers (they end up in the MCP tool schema) but are equally suitable
for REST clients reading the OpenAPI doc.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    """Payload for creating a project.

    A project is a workspace-scoped container that groups skills, agents,
    MCP server instances, and uploaded files under a shared identity and
    optional parent project.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Human-readable project name (unique per workspace).",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Short summary of the project's purpose.",
    )
    instructions: str | None = Field(
        default=None,
        max_length=20000,
        description="System-level instructions or notes shared across the project's agents.",
    )
    parent_project_id: str | None = Field(
        default=None,
        description="UUID of the parent project, if this is a sub-project.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name cannot be empty or whitespace")
        return v


class ProjectUpdate(BaseModel):
    """Patch payload for a project. All fields optional — unset = unchanged."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New project name.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="New project description.",
    )
    instructions: str | None = Field(
        default=None,
        max_length=20000,
        description="New project-level instructions.",
    )
    parent_project_id: str | None = Field(
        default=None,
        description="New parent project UUID, or null to detach.",
    )
