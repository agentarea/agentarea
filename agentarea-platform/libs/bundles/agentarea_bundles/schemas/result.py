"""Install-result contract returned after a package is installed."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentarea_bundles.schemas.preview import EntityKind


class InstallAction(StrEnum):
    CREATED = "created"
    UPDATED = "updated"  # created by an earlier install of this bundle, changed in place
    UNCHANGED = "unchanged"  # created by an earlier install of this bundle, left as is
    ORPHANED = "orphaned"  # created by an earlier install, no longer in the bundle; kept
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
    fingerprint: str | None = Field(
        default=None,
        description="sha256 of the resolved non-secret spec last applied; a redeploy diffs on it.",
    )


class InstallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_name: str
    installed_bundle_id: str | None = Field(default=None)
    entities: list[InstalledEntity] = Field(default_factory=list)
    setup_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret setup values supplied to installs of this bundle, reused on redeploy.",
    )
