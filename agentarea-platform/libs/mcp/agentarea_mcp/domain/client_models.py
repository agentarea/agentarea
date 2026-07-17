"""Client (agent-proxy) domain models.

A Client is a governable principal that is *not* runnable — it represents an
external harness (codex, claude-code, …) that pulls a scoped set of MCP server
instances and skills. Its tool set is either its own attachments, the ones
pulled from a source Project, or the union of both.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from agentarea_agents.domain.skill_models import Skill

    from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance

client_skills = sa.Table(
    "client_skills",
    BaseModel.metadata,
    sa.Column(
        "client_id",
        PG_UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "skill_id",
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

client_mcp_instances = sa.Table(
    "client_mcp_instances",
    BaseModel.metadata,
    sa.Column(
        "client_id",
        PG_UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "mcp_instance_id",
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("namespace_prefix", String(64), nullable=True),
)


class Client(BaseModel, WorkspaceScopedMixin):
    """An external harness registered as a governable, non-runnable principal."""

    __tablename__ = "clients"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="harness")
    source_project_id: Mapped[str | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )

    skills: Mapped[list[Skill]] = relationship(
        "Skill",
        secondary=client_skills,
        lazy="selectin",
        uselist=True,
    )
    mcp_instances: Mapped[list[MCPServerInstance]] = relationship(
        "MCPServerInstance",
        secondary=client_mcp_instances,
        lazy="selectin",
        uselist=True,
    )
