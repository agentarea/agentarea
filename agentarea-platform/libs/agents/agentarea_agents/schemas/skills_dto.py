"""Skill CRUD DTOs — single source of truth for REST, MCP toolset, and service layer.

Skills are file packages (SKILL.md plus optional helpers) that can be authored
inline (file map), uploaded as a ZIP, or imported from a public GitHub repo.
The DTOs below mirror the four mutation verbs exposed by the REST router and
the MCP toolset:

- ``SkillCreateFromContent`` — create from raw markdown content (single file).
- ``SkillCreateFromFiles`` — create from an inline ``{path: text}`` map.
- ``SkillCreateFromArchive`` — create from a base64 ZIP payload.
- ``SkillImportFromGithub`` — clone + parse a public GitHub repo.
- ``SkillEditMetadata`` — patch ``name`` / ``description`` only.
- ``SkillEditContent`` — replace the file tree (mode-aware).

Field descriptions are written for LLM consumers (they end up in the MCP tool
schema) and double as REST OpenAPI doc.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillCreateFromContent(BaseModel):
    """Create a content-mode skill from raw markdown.

    Use when the skill is a single ``SKILL.md`` document and no helper files
    are needed. The content may include YAML frontmatter; ``name`` and
    ``description`` default to the parsed frontmatter values.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        min_length=1,
        description="Raw markdown content of SKILL.md (optionally with YAML frontmatter).",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Override skill name (defaults to frontmatter 'name').",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Override skill description (defaults to frontmatter 'description').",
    )


class SkillCreateFromFiles(BaseModel):
    """Create a package-mode skill from an inline ``{path: text}`` map.

    Must include a root-level ``SKILL.md`` (case-insensitive). Limits:
    200 files, 5 MB total. For larger or binary packages use the archive
    variant instead.
    """

    model_config = ConfigDict(extra="forbid")

    files: dict[str, str] = Field(
        description=(
            "Map of relative path -> UTF-8 file text. Must include SKILL.md "
            "at the root. Max 200 files, 5 MB total."
        ),
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Override skill name (defaults to SKILL.md frontmatter).",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Override skill description (defaults to SKILL.md frontmatter).",
    )


class SkillCreateFromArchive(BaseModel):
    """Create a package-mode skill from a base64-encoded ZIP archive.

    Use for binary helpers, larger bundles, or pre-built packages. For
    inline text-only packages prefer :class:`SkillCreateFromFiles`.
    """

    model_config = ConfigDict(extra="forbid")

    zip_base64: str = Field(
        min_length=1,
        description="Base64-encoded ZIP archive containing SKILL.md and helper files.",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Override skill name (defaults to SKILL.md frontmatter).",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Override skill description (defaults to SKILL.md frontmatter).",
    )


class SkillImportFromGithub(BaseModel):
    """Import skill package(s) from a public GitHub repository URL."""

    model_config = ConfigDict(extra="forbid")

    github_url: str = Field(
        min_length=1,
        description="Public GitHub repository URL (e.g. 'https://github.com/owner/repo').",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Override skill name (defaults to repo's SKILL.md frontmatter).",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Override skill description (defaults to repo's SKILL.md frontmatter).",
    )
    skill_name: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Optional selector for repositories containing multiple SKILL.md files. "
            "Matches frontmatter name or package path."
        ),
    )
    import_all: bool = Field(
        default=False,
        description="Import every SKILL.md candidate found in the repository or tree path.",
    )

    @field_validator("github_url")
    @classmethod
    def _strip_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("github_url cannot be empty or whitespace")
        return v


class SkillEditMetadata(BaseModel):
    """Patch a skill's metadata (name and/or description). Never touches files.

    All fields optional — unset = unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New skill name.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="New skill description.",
    )


class SkillEditContent(BaseModel):
    """Replace a skill's file content. Mode-aware:

    - Content-mode skill (single SKILL.md, no S3 package): only accepts a
      single ``SKILL.md`` entry; multi-file payloads are rejected.
    - Package-mode skill: replaces the package in place — overwrites by
      path, deletes orphans not in the new map.
    """

    model_config = ConfigDict(extra="forbid")

    files: dict[str, str] = Field(
        description=(
            "Map of relative path -> UTF-8 file text. Must include SKILL.md "
            "at the root. Max 200 files, 5 MB total."
        ),
    )


class SkillSummary(BaseModel):
    """Lightweight skill reference returned by list/create-style tools."""

    id: str
    name: str
    description: str | None = None
    source_type: str
