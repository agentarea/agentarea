"""Task domain models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class Task(BaseModel):
    """Task domain model."""
    
    id: UUID
    agent_id: UUID
    description: str
    parameters: dict[str, Any]
    status: str  # pending, running, completed, failed, cancelled
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_id: str | None = None  # Temporal workflow execution ID
    user_id: str | None = None
    metadata: dict[str, Any] = {}

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    """Task creation model."""
    
    agent_id: UUID
    description: str
    parameters: dict[str, Any] = {}
    user_id: str | None = None
    metadata: dict[str, Any] = {}


class TaskUpdate(BaseModel):
    """Task update model."""
    
    status: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_id: str | None = None
    metadata: dict[str, Any] | None = None


# Legacy SimpleTask model for A2A compatibility
class SimpleTask(BaseModel):
    """Legacy task model for A2A protocol compatibility."""
    
    id: UUID
    title: str
    description: str
    query: str
    user_id: str
    agent_id: UUID
    status: str = "submitted"
    task_parameters: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime = datetime.utcnow()
    
    class Config:
        from_attributes = True