"""ORM models for the workspaces domain."""

from agentarea_common.base.models import BaseModel
from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class WorkspaceSettings(BaseModel):
    """Per-workspace configuration row.

    One row per workspace, lazily upserted on first save. Holds settings
    that don't naturally live on resources (budget cap, future: timezone,
    retention). Workspace itself is still represented as a string everywhere
    via WorkspaceScopedMixin; this table just hangs config off that string.
    """

    __tablename__ = "workspace_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_workspace_settings_workspace_id"),
    )

    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    monthly_cap_usd: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
