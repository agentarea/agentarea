"""Client (agent-proxy) domain models.

A Client is a governable principal that is *not* runnable — it represents an
external harness (codex, claude-code, …) that connects to a scoped set of MCP
server instances, OpenAPI connections, platform toolsets, and skills. Its tool
set is exactly its own attachments.

A client of a kind a runner drives (Codex, Claude Code) can also execute agents'
turns: its runner holds the client's key, keeps one socket to the platform and
runs each turn on the CLI's subscription, with the client's tools (ADR-0051).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from agentarea_agents.domain.skill_models import Skill

    from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance

# The client kinds a runner drives: a client of one of them can execute agents' turns.
# Codex and Claude Code have drivers of their own; the rest speak the Agent Client
# Protocol, and ``acp`` is any other ACP command its runner is started with.
RUNNER_KINDS = ("codex", "claude", "opencode", "gemini", "qwen", "goose", "cursor", "acp")

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
    # Tool names of the instance the client serves; NULL serves every tool.
    sa.Column("allowed_tools", sa.JSON, nullable=True),
)

# The link alone, with no relationship: an OpenAPI connection is another library's
# model, resolved by the repository's join where the client is read.
client_openapi_connections = sa.Table(
    "client_openapi_connections",
    BaseModel.metadata,
    sa.Column(
        "client_id",
        PG_UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "openapi_connection_id",
        PG_UUID(as_uuid=True),
        ForeignKey("openapi_connections.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("namespace_prefix", String(64), nullable=True),
    # Operation names of the connection the client serves; NULL serves every one.
    sa.Column("allowed_tools", sa.JSON, nullable=True),
)

# Platform toolsets (``agentarea/runs``, ...) are code, not rows, so the link
# names one by namespace instead of by foreign key.
client_platform_toolsets = sa.Table(
    "client_platform_toolsets",
    BaseModel.metadata,
    sa.Column(
        "client_id",
        PG_UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("toolset", String(128), primary_key=True),
    sa.Column("disabled_methods", sa.JSON, nullable=True),
)


@dataclass(frozen=True)
class ClientMcpInstanceLink:
    """How a client serves one attached MCP instance."""

    namespace_prefix: str | None
    # None serves every tool of the instance.
    allowed_tools: list[str] | None


@dataclass(frozen=True)
class ClientOpenAPIConnectionLink:
    """An OpenAPI connection a client carries, and how it serves it."""

    connection_id: str
    name: str
    namespace_prefix: str | None
    # None serves every operation of the connection.
    allowed_tools: list[str] | None


@dataclass(frozen=True)
class ClientPlatformToolset:
    """A platform toolset attached to a client, minus the methods it leaves out."""

    toolset: str
    disabled_methods: list[str] | None


class Client(BaseModel, WorkspaceScopedMixin):
    """An external harness registered as a governable, non-runnable principal."""

    __tablename__ = "clients"

    #: Governed by the authorization graph: creating one writes
    #: ``resource:<id>`` tuples so its creator can reach it afterwards.
    __graph_resource__ = True

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="harness")
    # [{name, reasoning_levels, default_reasoning}], as the client's runner reports them.
    models: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # The CLI's own name of the model turns use unless a task names one; None leaves the CLI's.
    default_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Hosts the CLI's sandbox reaches during a turn, beside those its runner allows.
    allow_domains: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    # Whether the CLI's commands run sandboxed: the task's folder and the allowed
    # hosts only. Off, they run unconfined on the runner's machine.
    sandbox: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
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
