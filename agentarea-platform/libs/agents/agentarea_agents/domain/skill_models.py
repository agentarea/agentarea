"""Skill domain model."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class SkillSourceType(StrEnum):
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
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_skills_workspace_slug"),
        # Provenance uniqueness is per-workspace: a built-in catalog item is forked
        # copy-on-write into each workspace, so the same registry_item_id may recur
        # across workspaces but never within one (operator dedup target).
        Index(
            "uq_skills_registry_item",
            "workspace_id",
            "registry_item_id",
            unique=True,
            postgresql_where=text("registry_item_id IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Immutable, workspace-scoped human-readable identifier (derived from name at creation).
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
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
    # Provenance: links back to the registry catalog item this skill was created from
    registry_item_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, default=None
    )
    network_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="private")

    # Relationships
    # Element type stays untyped on purpose: importing Agent here — even under
    # TYPE_CHECKING — reintroduces a module-level import cycle with
    # agentarea_agents.domain.models, which imports Skill for Agent.skills.
    # The mapper target is resolved from the "Agent" registry name below.
    agents: Mapped[list[Any]] = relationship(
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


# Self-referential association table for Skill members (skill-as-bundle pattern)
skill_members_table = Table(
    "skill_members",
    BaseModel.metadata,
    Column(
        "parent_skill_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "child_skill_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("order", Integer, nullable=False, default=0),
    Column("is_required", Boolean, nullable=False, default=True),
    # List of child_skill_id strings that must execute before this child
    Column("dependencies", JSON, nullable=False, default=list),
)


class SkillMember:
    """Wrapper class for skill_members self-referential association table.

    Tracks child skills within a parent skill (skill-as-bundle pattern).
    Agents attach a Skill normally; if that Skill has members, they are
    resolved at execution time via topological sort.
    """

    __table__ = skill_members_table

    def __init__(
        self,
        parent_skill_id: Any,
        child_skill_id: Any,
        order: int = 0,
        is_required: bool = True,
        dependencies: list[str] | None = None,
    ):
        self.parent_skill_id = parent_skill_id
        self.child_skill_id = child_skill_id
        self.order = order
        self.is_required = is_required
        self.dependencies = dependencies or []
