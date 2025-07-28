from datetime import datetime
from uuid import UUID, uuid4

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin, AuditMixin
from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class Agent(BaseModel, WorkspaceScopedMixin, AuditMixin):
    """Agent model with workspace awareness and audit trail."""
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    description: Mapped[str] = mapped_column(String, nullable=True)
    instruction: Mapped[str] = mapped_column(String, nullable=True)
    model_id: Mapped[str] = mapped_column(String, nullable=True)
    tools_config: Mapped[dict] = mapped_column(JSON, nullable=True)
    events_config: Mapped[dict] = mapped_column(JSON, nullable=True)
    planning: Mapped[bool] = mapped_column(Boolean, nullable=True)

    # Relationships
    # chat_sessions = relationship("ChatSession", back_populates="agent")  # Disabled - ChatSession model not implemented
