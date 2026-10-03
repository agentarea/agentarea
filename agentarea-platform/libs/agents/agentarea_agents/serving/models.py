from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

REVISION_ACTIVE = "active"
REVISION_CANDIDATE = "candidate"
REVISION_ARCHIVED = "archived"

EXPERIMENT_RUNNING = "running"
EXPERIMENT_STOPPED = "stopped"
EXPERIMENT_PROMOTED = "promoted"

_JSONB = JSON().with_variant(JSONB(), "postgresql")


class AgentRevision(BaseModel, WorkspaceScopedMixin):
    """An immutable snapshot of what an agent runs.

    ``status`` is ``active`` for the revision the agent's pointer serves,
    ``candidate`` for one proposed but never served, ``archived`` for one that
    served before. ``spec`` never changes after insert.
    """

    __tablename__ = "agent_revisions"
    __table_args__ = (UniqueConstraint("agent_id", "number", name="uq_agent_revisions_number"),)

    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    spec: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(_JSONB, nullable=False, default=list)


class AgentExperiment(BaseModel, WorkspaceScopedMixin):
    """A live split between the serving revision and one candidate.

    ``weights`` maps arm name (``control``/``candidate``) to a share of runs in
    percent. At most one experiment per agent is running.
    """

    __tablename__ = "agent_experiments"
    __table_args__ = (
        Index(
            "uq_agent_experiments_running",
            "agent_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    control_revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_revisions.id", ondelete="CASCADE"), nullable=False
    )
    candidate_revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_revisions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    weights: Mapped[dict[str, int]] = mapped_column(_JSONB, nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False)
    decisions: Mapped[list[dict[str, Any]]] = mapped_column(_JSONB, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
