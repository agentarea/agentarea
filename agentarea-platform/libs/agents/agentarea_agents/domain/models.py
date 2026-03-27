from typing import TYPE_CHECKING

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from agentarea_agents.domain.skill_models import Skill


class Agent(BaseModel, WorkspaceScopedMixin):
    """Agent model with workspace awareness and audit trail."""

    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    description: Mapped[str] = mapped_column(String, nullable=True)
    instruction: Mapped[str] = mapped_column(String, nullable=True)
    model_id: Mapped[str] = mapped_column(String, nullable=True)
    tools: Mapped[dict[str, any] | None] = mapped_column(JSON, nullable=True)
    events_config: Mapped[dict[str, any] | None] = mapped_column(JSON, nullable=True)
    planning: Mapped[bool] = mapped_column(Boolean, nullable=True)
    a2ui_enabled: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    agent_type: Mapped[str] = mapped_column(String, nullable=False, default="stateless")

    # Relationships
    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        secondary="agent_skills",
        back_populates="agents",
    )
