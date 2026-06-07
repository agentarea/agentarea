"""Install-result contract returned after a package is installed."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agentarea_bundles.schemas.preview import EntityKind


class InstallAction(StrEnum):
    CREATED = "created"
    REUSED = "reused"  # already existed in the workspace, linked instead of duplicated
    SKIPPED = "skipped"  # unsupported / not installable


class InstalledEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    key: str
    name: str
    action: InstallAction
    id: str | None = Field(default=None, description="Created/reused entity id, when applicable.")
    detail: str | None = Field(default=None)


class InstallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_name: str
    installed_bundle_id: str | None = Field(default=None)
    entities: list[InstalledEntity] = Field(default_factory=list)
