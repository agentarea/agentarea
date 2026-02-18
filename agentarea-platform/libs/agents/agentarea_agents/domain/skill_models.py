"""Skill domain model."""

from datetime import datetime
from enum import Enum
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class SkillSourceType(str, Enum):
    """Source type for a skill package."""

    CONTENT = "content"  # Raw markdown content
    ZIP = "zip"  # Uploaded ZIP file
    GITHUB = "github"  # GitHub repository
    PATH = "path"  # Local path (declarative import)


class Skill(BaseModel, WorkspaceScopedMixin):
    """Skill model with workspace awareness.

    A skill is a reusable capability that can be attached to agents.
    Skills follow the Claude Code Skills format with YAML frontmatter.
    """

    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default=SkillSourceType.CONTENT.value
    )
    source_url: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )  # GitHub URL or original source
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # Main skill markdown content
    s3_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )  # S3 path for multi-file packages

    # Relationships
    agents: Mapped[list["Agent"]] = relationship(
        "Agent",
        secondary="agent_skills",
        back_populates="skills",
    )

    def __repr__(self) -> str:
        """Return a compact string representation."""
        return f"<Skill {self.name} ({self.id})>"


# Association table for Agent-Skill many-to-many relationship
# Using Table construct to match the database schema exactly
agent_skills_table = Table(
    "agent_skills",
    BaseModel.metadata,
    Column(
        "agent_id",
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "skill_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime, nullable=False, default=datetime.now),
)


# Class-based wrapper for type hints and queries
class AgentSkill:
    """Wrapper class for agent_skills association table.

    This class provides a type-safe way to reference the association table
    in queries without inheriting from BaseModel (which would add an id column).
    """

    __table__ = agent_skills_table

    def __init__(self, agent_id: Any, skill_id: Any, created_at: datetime | None = None):
        self.agent_id = agent_id
        self.skill_id = skill_id
        self.created_at = created_at or datetime.now()


# Import Agent for type hints (avoid circular import at runtime)
from agentarea_agents.domain.models import Agent  # noqa: E402
