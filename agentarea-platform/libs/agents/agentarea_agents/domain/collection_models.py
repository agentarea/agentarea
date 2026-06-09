"""Skill collection domain model.

A skill collection groups skills together so that a single ReBAC grant on the
collection fans out to every skill it contains (see the Keto ``SkillCollection``
namespace). Collections are workspace-scoped, mirroring the skills they hold.
"""

from datetime import datetime
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class SkillCollection(BaseModel, WorkspaceScopedMixin):
    """A workspace-scoped grouping of skills.

    The collection's UUID is used directly as the Keto ``SkillCollection``
    object id; grants on it fan out to every contained skill.
    """

    __tablename__ = "skill_collections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_skill_collections_workspace_slug"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Workspace-unique human-readable identifier.
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    skills: Mapped[list["Skill"]] = relationship(
        "Skill",
        secondary="collection_skills",
    )

    def __repr__(self) -> str:
        """Return a compact string representation."""
        return f"<SkillCollection {self.name} ({self.id})>"


# Association table for SkillCollection-Skill many-to-many relationship.
# Mirrors agent_skills: composite primary key + CASCADE deletes + created_at.
collection_skills_table = Table(
    "collection_skills",
    BaseModel.metadata,
    Column(
        "collection_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skill_collections.id", ondelete="CASCADE"),
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


class CollectionSkill:
    """Wrapper class for the collection_skills association table.

    Provides a type-safe reference to the association table in queries without
    inheriting from BaseModel (which would add an id column).
    """

    __table__ = collection_skills_table

    def __init__(self, collection_id: Any, skill_id: Any, created_at: datetime | None = None):
        self.collection_id = collection_id
        self.skill_id = skill_id
        self.created_at = created_at or datetime.now()


# Import Skill for type hints (avoid circular import at runtime)
from agentarea_agents.domain.skill_models import Skill  # noqa: E402
