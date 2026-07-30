"""Task domain models."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class Task(BaseModel):
    """Task domain model."""

    id: UUID
    agent_id: UUID
    description: str
    parameters: dict[str, Any]
    status: str  # pending, running, blocked, completed, failed, cancelled
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime  # Added to match BaseModel
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_id: str | None = None  # Temporal workflow execution ID
    user_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("result", mode="before")
    @classmethod
    def validate_result(cls, v):
        """Coerce non-dict result values into a dict wrapper."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"response": v}

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_task_metadata(cls, v):
        """Ensure metadata is always a dict, converting non-dict values to empty dict."""
        if v is not None and not isinstance(v, dict):
            # Convert non-dict values (like SQLAlchemy MetaData) to empty dict
            return {}
        return v or {}

    def __setattr__(self, name, value):
        """Custom setter to validate metadata field when manually assigned."""
        if name == "metadata":
            if value is not None and not isinstance(value, dict):
                # Convert non-dict values (like SQLAlchemy MetaData) to empty dict
                value = {}
        super().__setattr__(name, value)

    class Config:
        """Pydantic model configuration."""

        from_attributes = True


class TaskCreate(BaseModel):
    """Task creation model."""

    agent_id: UUID
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    workspace_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_task_create_metadata(cls, v):
        """Convert non-dict metadata to empty dict."""
        if v is not None and not isinstance(v, dict):
            return {}
        return v or {}

    def __setattr__(self, name, value):
        """Custom setter to validate metadata field when manually assigned."""
        if name == "metadata" and value is not None and not isinstance(value, dict):
            # Convert non-dict values (like SQLAlchemy MetaData) to empty dict
            value = {}
        super().__setattr__(name, value)

    @classmethod
    def model_validate(cls, obj, *, strict=None, from_attributes=None, context=None):
        """Override model validation to handle metadata conversion."""
        if (
            hasattr(obj, "metadata")
            and obj.metadata is not None
            and not isinstance(obj.metadata, dict)
        ):
            # Create a copy and fix the metadata
            if hasattr(obj, "__dict__"):
                obj_dict = obj.__dict__.copy()
                obj_dict["metadata"] = {}
                return super().model_validate(
                    obj_dict, strict=strict, from_attributes=from_attributes, context=context
                )
        return super().model_validate(
            obj, strict=strict, from_attributes=from_attributes, context=context
        )


class TaskUpdate(BaseModel):
    """Task update model."""

    status: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_id: str | None = None
    task_parameters: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("result", mode="before")
    @classmethod
    def validate_result(cls, v):
        """Coerce non-dict result values into a dict wrapper."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"response": v}

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_task_update_metadata(cls, v):
        """Ensure metadata is always a dict, converting non-dict values to empty dict."""
        if v is not None and not isinstance(v, dict):
            # Convert non-dict values (like SQLAlchemy MetaData) to empty dict
            return {}
        return v

    def __setattr__(self, name, value):
        """Custom setter to validate metadata field when manually assigned."""
        if name == "metadata" and value is not None and not isinstance(value, dict):
            # Convert non-dict values (like SQLAlchemy MetaData) to empty dict
            value = {}
        super().__setattr__(name, value)


# Service/API-layer task model for A2A compatibility and task management
class AgentTask(BaseModel):
    """Task model for A2A protocol compatibility and task management.

    The richer service/API-layer view of a task: it carries the lifecycle and
    A2A fields (title, query, task_parameters, effective_policy, timestamps)
    on top of the basic ``Task`` domain model it is converted to/from at the
    repository boundary.
    """

    # Original fields (maintained for backward compatibility)
    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str
    query: str
    user_id: str
    workspace_id: str  # Required for proper multi-tenancy isolation
    agent_id: UUID
    status: str = "submitted"
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Enhanced fields for task lifecycle management
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_id: str | None = None  # Temporal workflow execution ID or other execution identifier
    metadata: dict[str, Any] = Field(default_factory=dict)  # Additional task metadata
    effective_policy: dict[str, Any] | None = None  # Resolved governance policy passed to execution

    @field_validator("result", mode="before")
    @classmethod
    def validate_result(cls, v):
        """Coerce non-dict result values into a dict wrapper."""
        if v is None:
            return None
        if isinstance(v, dict):
            return v
        return {"response": v}

    class Config:
        """Pydantic model configuration."""

        from_attributes = True

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization validation and field setup."""
        # Set updated_at to created_at if not provided (backward compatibility)
        if self.updated_at is None:
            self.updated_at = self.created_at

        # Validate datetime field relationships
        self._validate_datetime_fields()

    def _validate_datetime_fields(self) -> None:
        """Surface illogical datetime relationships without breaking hydration.

        This runs on every construction, including loading existing rows from
        the database. Raising here would make any task with inconsistent
        timestamps un-loadable and 500 every read path that touches it (e.g. the
        SSE event stream). Such skew exists in practice — e.g. a past bulk
        migration that overwrote ``created_at`` while preserving the original
        ``started_at``. So we log a warning instead of raising: the signal is
        kept, but reads stay total.
        """
        if self.started_at and self.started_at < self.created_at:
            logger.warning(
                "Task %s has started_at (%s) before created_at (%s)",
                self.id,
                self.started_at,
                self.created_at,
            )

        if self.completed_at and self.started_at and self.completed_at < self.started_at:
            logger.warning(
                "Task %s has completed_at (%s) before started_at (%s)",
                self.id,
                self.completed_at,
                self.started_at,
            )

        if self.completed_at and self.completed_at < self.created_at:
            logger.warning(
                "Task %s has completed_at (%s) before created_at (%s)",
                self.id,
                self.completed_at,
                self.created_at,
            )

    def is_completed(self) -> bool:
        """Check if the task is in a completed state."""
        return self.status in ["completed", "failed", "blocked", "cancelled"]

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
        self.updated_at = datetime.now(UTC)

        # Automatically set timestamps based on status
        if new_status == "running" and not self.started_at:
            self.started_at = self.updated_at
        elif (
            new_status in ["completed", "failed", "blocked", "cancelled"] and not self.completed_at
        ):
            self.completed_at = self.updated_at

        # Update any additional fields provided
        for field, value in kwargs.items():
            if hasattr(self, field):
                setattr(self, field, value)


class TaskEvent(BaseModel):
    """Task event domain model for event sourcing."""

    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    event_type: str
    timestamp: datetime
    data: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str  # Required - must be provided explicitly
    created_by: str  # Required - must be provided explicitly

    class Config:
        """Pydantic model configuration."""

        from_attributes = True

    @classmethod
    def create_workflow_event(
        cls,
        task_id: UUID,
        event_type: str,
        data: dict[str, Any],
        workspace_id: str,  # Required - no default
        created_by: str,  # Required - no default
    ) -> "TaskEvent":
        """Create a workflow event with proper formatting.

        Args:
            task_id: Task ID for the event
            event_type: Type of event
            data: Event data dictionary
            workspace_id: Workspace ID (required)
            created_by: User/entity that created the event (required)
        """
        return cls(
            task_id=task_id,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            data=data,
            metadata={"source": "workflow", "created_at": datetime.now(UTC).isoformat()},
            workspace_id=workspace_id,
            created_by=created_by,
        )
