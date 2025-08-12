"""Data models for agent execution workflows.

This module contains all dataclasses and type definitions used by the agent execution workflow.
"""

from dataclasses import dataclass, field
from typing import Any

# Define a simple Message class to avoid SDK imports in workflows
@dataclass 
class Message:
    """Simple message class for workflow use without SDK dependencies."""
    role: str
    content: str
    timestamp: str | None = None
    event_metadata: dict[str, Any] = field(default_factory=dict)  # Use event_metadata instead of metadata
    tool_call_id: str | None = None
    name: str | None = None
    function_call: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class AgentGoal:
    """Agent goal definition."""

    id: str
    description: str
    success_criteria: list[str]
    max_iterations: int
    requires_human_approval: bool
    context: dict[str, Any]


# Message classes moved to agentarea_agents_sdk for better organization


@dataclass
class ToolCall:
    """Structured tool call information."""

    id: str
    function: dict[str, Any]
    type: str = "function"


@dataclass
class ToolResult:
    """Result from tool execution."""

    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None


@dataclass
class WorkflowEvent:
    """Structured workflow event."""

    event_type: str
    data: dict[str, Any]
    timestamp: str | None = None
    iteration: int | None = None


@dataclass
class ExecutionResult:
    """Result from main execution loop."""

    iterations_completed: int
    success: bool
    final_response: str | None = None
    total_cost: float = 0.0


@dataclass
class AgentExecutionState:
    """Simplified execution state with direct attribute access."""

    execution_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    user_id: str = ""  # Add user_id field for user context
    goal: AgentGoal | None = None
    status: str = "initializing"  # Will be set to ExecutionStatus.INITIALIZING in workflow
    current_iteration: int = 0
    messages: list[Message] = field(default_factory=list)
    agent_config: dict[str, Any] = field(default_factory=dict)
    available_tools: list[dict[str, Any]] = field(default_factory=list)
    final_response: str | None = None
    success: bool = False
    budget_usd: float | None = None
    user_context_data: dict[str, Any] = field(default_factory=dict)