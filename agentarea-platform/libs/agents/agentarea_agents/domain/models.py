from typing import TYPE_CHECKING, Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from agentarea_agents.domain.skill_models import Skill


class Agent(BaseModel, WorkspaceScopedMixin):
    """Agent model with workspace awareness and audit trail."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),)

    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    instruction: Mapped[str | None] = mapped_column(String, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tools: Mapped[list[dict[str, Any]] | dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    events_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    planning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    a2ui_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    agent_type: Mapped[str] = mapped_column(String, nullable=False, default="stateless")
    # Forward provenance link to the catalog item this agent was forked from
    # (copy-on-write). Null for agents created from scratch. See ADR-003.
    registry_item_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Relationships
    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        secondary="agent_skills",
        back_populates="agents",
    )
