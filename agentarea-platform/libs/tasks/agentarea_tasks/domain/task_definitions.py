"""Task definitions: the saved description of a task, apart from when it runs.

A definition names an agent, what to ask it and the parameters to ask with. It
runs on demand, and a trigger may point at one instead of carrying its own ask.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskDefinition(BaseModel):
    """A saved task: the agent, the text it is asked, and the parameters."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    agent_id: UUID
    parameters: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class TaskDefinitionNotFoundError(Exception):
    """No task definition with this id in the workspace."""

    def __init__(self, definition_id: UUID):
        self.definition_id = definition_id
        super().__init__(f"Task definition {definition_id} not found")


class TaskDefinitionValidationError(ValueError):
    """A task definition that cannot be saved as given."""


class TaskDefinitionInUseError(Exception):
    """Triggers run this definition, so it cannot change agent or be deleted under them."""
