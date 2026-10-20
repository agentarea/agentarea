"""Task domain models."""

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from agentarea_common.events.contract import require_known_type
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from agentarea_common.auth.context import UserContext

logger = logging.getLogger(__name__)


def _require_aware(v: datetime | None) -> datetime | None:
    """Reject naive datetimes for scheduling.

    A future instant without an offset is ambiguous, and the neighbouring
    ``started_at`` / ``completed_at`` columns are naive — assuming UTC here
    would silently shift a run by hours.
    """
    if v is not None and v.tzinfo is None:
        raise ValueError("scheduled_at must be timezone-aware")
    return v


class TaskProvenance(BaseModel):
    """Why a task exists: who or what started it, and the event that caused it."""

    origin_type: Literal["user", "trigger", "agent", "api", "a2a"] | None = None
    origin_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    parent_task_id: UUID | None = None
    #: The causation depth of the event that started the task; 0 when none did.
    depth: int = 0
    #: The saved task definition the run was asked from, if any.
    task_definition_id: UUID | None = None
    #: Who started the run, as ``<kind>:<id>`` (``user:<id>``, ``client:<id>``);
    #: ``None`` when nothing human did (a schedule, an event). It narrows the run
    #: and is recorded; it never lends the run its own authority.
    source_identity: str | None = None

    @classmethod
    def started_by(cls, user_id: str, *, via_api_key: bool) -> "TaskProvenance":
        """A run a person started from the app, the API or MCP."""
        return cls(
            origin_type="api" if via_api_key else "user",
            origin_id=user_id,
            source_identity=f"user:{user_id}",
        )

    @classmethod
    def started_by_caller(cls, caller: "UserContext") -> "TaskProvenance":
        """A run ``caller`` started: a person from the app, API or MCP, or an agent in its run.

        An agent starting a run is recorded as the agent. The person its own run
        is attributed to did not start this one, so no person narrows it.
        """
        if caller.subject is not None and caller.subject.kind == "agent":
            return cls(origin_type="agent", origin_id=caller.subject.id)
        credential = caller.credential
        return cls.started_by(
            caller.user_id,
            via_api_key=credential is not None and credential.kind == "api_key",
        )

    @property
    def source_user_id(self) -> str | None:
        """The person who started the run, if a person did."""
        if self.source_identity and self.source_identity.startswith("user:"):
            return self.source_identity.removeprefix("user:")
        return None


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
    scheduled_at: datetime | None = None  # One-shot future run; None means run now
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: TaskProvenance = Field(default_factory=TaskProvenance)

    _validate_scheduled_at = field_validator("scheduled_at")(_require_aware)

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
    scheduled_at: datetime | None = None  # One-shot future run; None means run now
    metadata: dict[str, Any] = Field(default_factory=dict)  # Additional task metadata
    effective_policy: dict[str, Any] | None = None  # Resolved governance policy passed to execution
    provenance: TaskProvenance = Field(default_factory=TaskProvenance)

    _validate_scheduled_at = field_validator("scheduled_at")(_require_aware)

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
        event_id: UUID,
        event_type: str,
        data: dict[str, Any],
        timestamp: datetime,
        workspace_id: str,  # Required - no default
        created_by: str,  # Required - no default
    ) -> TaskEvent:
        """Create a workflow event with the identity the workflow minted.

        ``event_id`` and ``timestamp`` come from the workflow, so a retried
        publish of the same event maps to the same row. A type outside the
        closed vocabulary raises ``UnknownEventTypeError``.
        """
        return cls(
            id=event_id,
            task_id=task_id,
            event_type=require_known_type(event_type),
            timestamp=timestamp,
            data=data,
            metadata={"source": "workflow", "created_at": datetime.now(UTC).isoformat()},
            workspace_id=workspace_id,
            created_by=created_by,
        )


class ConversationEntry(BaseModel):
    """One row of a task's log at its position: a message, a compaction or an event.

    A ``compaction`` holds the summary of everything before it and, in
    ``meta["skills"]``, the text of the skills loaded so far. An ``event`` is a
    moment the feed shows (its type in ``name``, details in ``meta``) and the
    model never sees.
    """

    seq: int
    kind: str = "message"
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    # Images a tool returned, by reference: ``{"id", "mime_type", "size"}`` each.
    attachments: list[dict[str, Any]] | None = None
    event_id: UUID | None = None
    execution_id: str | None = None
    iteration: int | None = None
    meta: dict[str, Any] | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    # Where the body of a row too large to keep inline is stored; content is then empty.
    body_ref: str | None = None
    # When the row's moment happened; the store's clock when None.
    occurred_at: datetime | None = None

    def as_message(self) -> dict[str, Any]:
        """The entry as a chat message, without the fields it does not set."""
        content = self.content
        if self.kind == "compaction":
            content = "\n\n".join([content, *((self.meta or {}).get("skills") or [])])
        message: dict[str, Any] = {"role": self.role, "content": content}
        for key in ("tool_call_id", "name", "tool_calls", "attachments"):
            value = getattr(self, key)
            if value is not None:
                message[key] = value
        return message
