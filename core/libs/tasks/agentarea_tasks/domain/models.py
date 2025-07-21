"""Task domain models."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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
    updated_at: datetime  # Added to match BaseModel
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


# Enhanced SimpleTask model for A2A compatibility and task management
class SimpleTask(BaseModel):
    """Enhanced task model for A2A protocol compatibility and task management.
    
    This model extends the original SimpleTask with additional fields for
    enhanced task lifecycle management while maintaining backward compatibility.
    """

    # Original fields (maintained for backward compatibility)
    id: UUID = Field(default_factory=uuid4)
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

    # Enhanced fields for task lifecycle management
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_id: str | None = None  # Temporal workflow execution ID or other execution identifier
    metadata: dict[str, Any] = {}  # Additional metadata for task management

    class Config:
        from_attributes = True

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization validation and field setup."""
        # Set updated_at to created_at if not provided (backward compatibility)
        if self.updated_at is None:
            self.updated_at = self.created_at

        # Validate datetime field relationships
        self._validate_datetime_fields()

    def _validate_datetime_fields(self) -> None:
        """Validate that datetime fields have logical relationships."""
        # started_at should not be before created_at
        if self.started_at and self.started_at < self.created_at:
            raise ValueError("started_at cannot be before created_at")

        # completed_at should not be before started_at
        if self.completed_at and self.started_at and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")

        # completed_at should not be before created_at
        if self.completed_at and self.completed_at < self.created_at:
            raise ValueError("completed_at cannot be before created_at")

    def is_completed(self) -> bool:
        """Check if the task is in a completed state."""
        return self.status in ["completed", "failed", "cancelled"]

    def is_running(self) -> bool:
        """Check if the task is currently running."""
        return self.status == "running"

    def update_status(self, new_status: str, **kwargs) -> None:
        """Update task status with automatic timestamp management.
        
        Args:
            new_status: The new status to set
            **kwargs: Additional fields to update
        """
        from datetime import datetime

        self.status = new_status
        self.updated_at = datetime.utcnow()

        # Automatically set timestamps based on status
        if new_status == "running" and not self.started_at:
            self.started_at = self.updated_at
        elif new_status in ["completed", "failed", "cancelled"] and not self.completed_at:
            self.completed_at = self.updated_at

        # Update any additional fields provided
        for field, value in kwargs.items():
            if hasattr(self, field):
                setattr(self, field, value)
