"""Simple task domain models for AgentArea platform.

These models represent the minimal task entities needed for agent execution.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SimpleTask(BaseModel):
    """Simple task entity for agent execution.
    
    This is a minimal representation that matches what agent_runner_service actually uses.
    """
    
    # Core identification
    id: UUID = Field(default_factory=lambda: UUID("00000000-0000-0000-0000-000000000000"))  # Will be set by DB
    title: str
    description: str
    query: str  # The actual instruction/question for the agent
    
    # Execution context
    status: str = "submitted"  # submitted, working, completed, failed
    user_id: str
    agent_id: UUID
    
    # Optional parameters and results
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error_message: str | None = None
    
    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
