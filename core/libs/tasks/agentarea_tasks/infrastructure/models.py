"""SQLAlchemy models for tasks infrastructure.

Simplified task model that matches the agent_runner_service requirements.
"""

from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel
from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class Task(BaseModel):
    """SQLAlchemy Task model for simple agent task execution."""

    __tablename__ = "tasks"

    # Inherits id (UUID), created_at, updated_at from BaseModel
    
    # Core task information
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)  # The actual instruction/question
    
    # Execution context
    status: Mapped[str] = mapped_column(String, nullable=False, default="submitted")
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    
    # Optional execution data
    task_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True) 
    error_message: Mapped[str] = mapped_column(Text, nullable=True) 