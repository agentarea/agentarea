"""Project domain models."""

import sqlalchemy as sa
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Junction table: project <-> skills
project_skills = Table(
    "project_skills",
    BaseModel.metadata,
    sa.Column(
        "project_id",
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "skill_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Junction table: project <-> mcp_server_instances
project_mcp_instances = Table(
    "project_mcp_instances",
    BaseModel.metadata,
    sa.Column(
        "project_id",
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "mcp_instance_id",
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Junction table: project <-> agents
project_agents = Table(
    "project_agents",
    BaseModel.metadata,
    sa.Column(
        "project_id",
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "agent_id",
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Project(BaseModel, WorkspaceScopedMixin):
    """Project model — a container for agents, skills, MCP instances, and files."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_project_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    minio_prefix: Mapped[str] = mapped_column(String(500), nullable=False)

    # Relationships
    skills: Mapped[list] = relationship(
        "Skill",
        secondary=project_skills,
        lazy="selectin",
    )
    mcp_instances: Mapped[list] = relationship(
        "MCPServerInstance",
        secondary=project_mcp_instances,
        lazy="selectin",
    )
    agents: Mapped[list] = relationship(
        "Agent",
        secondary=project_agents,
        lazy="selectin",
    )
    children: Mapped[list["Project"]] = relationship(
        "Project",
        back_populates="parent",
        foreign_keys=[parent_project_id],
        lazy="select",
    )
    parent: Mapped["Project | None"] = relationship(
        "Project",
        back_populates="children",
        foreign_keys=[parent_project_id],
        remote_side="Project.id",
        lazy="select",
    )
