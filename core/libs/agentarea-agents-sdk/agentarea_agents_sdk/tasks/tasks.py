"""Task models for in-memory task management."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class TaskStatus(Enum):
    """Status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass
class Task:
    """A task with hierarchical support (parent/subtasks)."""

    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    id: UUID = field(default_factory=uuid4)
    parent_id: UUID | None = None
    priority: int = 1  # 1=low, 2=medium, 3=high
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self):
        """Set timestamps if not provided."""
        import datetime

        now = datetime.datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
