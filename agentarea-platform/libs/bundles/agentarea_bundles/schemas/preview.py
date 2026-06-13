"""Import-preview contract: the result of analyzing a package before install."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agentarea_bundles.schemas.bundle import Bundle, SetupField


class EntityKind(StrEnum):
    MCP = "mcp"
    SKILL = "skill"
    AGENT = "agent"
    AUTOMATION = "automation"
    POLICY = "policy"


class EntityStatus(StrEnum):
    WILL_CREATE = "will_create"
    ALREADY_EXISTS = "already_exists"
    UNSUPPORTED = "unsupported"


class IssueSeverity(StrEnum):
    BLOCK = "block"  # install cannot proceed
    WARN = "warn"  # install proceeds, entity may be skipped or degraded


class PreviewEntity(BaseModel):
    """One thing the package will (or won't) create."""

    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    key: str
    name: str
    status: EntityStatus
    detail: str | None = Field(default=None)


class PreviewIssue(BaseModel):
    """A problem found while analyzing the package."""

    model_config = ConfigDict(extra="forbid")

    severity: IssueSeverity
    message: str
    entity_key: str | None = Field(default=None)


class ImportPreview(BaseModel):
    """What the wizard renders before the user commits to installing."""

    model_config = ConfigDict(extra="forbid")

    bundle: Bundle
    setup: list[SetupField] = Field(default_factory=list)
    entities: list[PreviewEntity] = Field(default_factory=list)
    issues: list[PreviewIssue] = Field(default_factory=list)
    installable: bool = Field(
        description="True when there are no blocking issues (setup may still be required)."
    )

    @property
    def block_issues(self) -> list[PreviewIssue]:
        return [i for i in self.issues if i.severity is IssueSeverity.BLOCK]
