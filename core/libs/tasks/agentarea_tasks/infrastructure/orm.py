"""Task ORM models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel
from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class TaskORM(BaseModel):
    """Task ORM model."""
    
    __tablename__ = "tasks"
    
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    execution_id: Mapped[str] = mapped_column(String(255), nullable=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=True)
    task_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    
    def __repr__(self) -> str:
        return f"TaskORM(id={self.id}, agent_id={self.agent_id}, status={self.status})"