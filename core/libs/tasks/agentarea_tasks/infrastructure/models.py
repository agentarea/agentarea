"""SQLAlchemy models for tasks infrastructure.

This module provides SQLAlchemy ORM models that map to database tables
for task persistence operations.
"""

from datetime import datetime
from uuid import UUID

from agentarea_common.base.models import BaseModel
from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class Task(BaseModel):
    """SQLAlchemy Task model extending the common BaseModel."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=True)
    parent_task_id: Mapped[str] = mapped_column(String, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    complexity: Mapped[str] = mapped_column(String, nullable=False, default="moderate")
    assigned_agent_id: Mapped[str] = mapped_column(String, nullable=True)
    required_capabilities: Mapped[list] = mapped_column(JSON, nullable=True)
    collaboration: Mapped[dict] = mapped_column(JSON, nullable=True)
    status: Mapped[dict] = mapped_column(JSON, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    error_code: Mapped[str] = mapped_column(String, nullable=True)
    dependencies: Mapped[list] = mapped_column(JSON, nullable=True)
    subtasks: Mapped[list] = mapped_column(JSON, nullable=True)
    resources: Mapped[dict] = mapped_column(JSON, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=True)
    inputs: Mapped[list] = mapped_column(JSON, nullable=True)
    artifacts: Mapped[list] = mapped_column(JSON, nullable=True)
    history: Mapped[list] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    task_metadata: Mapped[dict] = mapped_column(JSON, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=True)
    organization_id: Mapped[str] = mapped_column(String, nullable=True)
    workspace_id: Mapped[str] = mapped_column(String, nullable=True) 