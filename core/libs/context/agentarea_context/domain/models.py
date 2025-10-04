from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import ContextScope, ContextType


class Context(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    content: str
    context_type: ContextType = ContextType.FACTUAL
    task_id: UUID | None = None
    agent_id: UUID | None = None
    workspace_id: str | None = None
    context_metadata: dict[str, Any] = Field(
        default_factory=dict
    )  # Renamed to avoid SQLAlchemy conflict
    score: float | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @property
    def scope(self) -> ContextScope:
        if self.task_id:
            return ContextScope.TASK
        elif self.agent_id:
            return ContextScope.AGENT
        else:
            return ContextScope.GLOBAL


class ContextEntry(BaseModel):
    context_id: UUID
    embedding: list[float]
    content_hash: str
