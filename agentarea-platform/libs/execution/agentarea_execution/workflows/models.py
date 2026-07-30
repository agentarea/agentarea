"""Data models for agent execution workflows.

This module contains all dataclasses and type definitions used by the agent execution workflow.
"""

from typing import Any

from agentarea_common.money import ZERO, Money
from pydantic import BaseModel, Field


# Define a simple Message class to avoid SDK imports in workflows
class Message(BaseModel):
    """Simple message class for workflow use without SDK dependencies."""

    role: str
    content: str
    timestamp: str | None = None
    # Use event_metadata instead of metadata
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class AgentGoal(BaseModel):
    """Agent goal definition."""

    id: str
    description: str
    success_criteria: list[str]
    max_iterations: int
    requires_human_approval: bool
    context: dict[str, Any]


# Message classes moved to agentarea_agents_sdk for better organization


class ToolCall(BaseModel):
    """Structured tool call information."""

    id: str
    function: dict[str, Any]
    type: str = "function"


class ToolResult(BaseModel):
    """Result from tool execution."""

    tool_call_id: str
    content: str
    success: bool = True
    error: str | None = None


class PendingEscalation(BaseModel):
    """Tracks a single tool call awaiting human approval."""

    escalation_id: str
    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    resolved: bool = False
    approved: bool | None = None
    deny_comment: str | None = None
    # Subject refs allowed to approve (from ApprovalPolicy.approvers); empty = any member
    approvers: list[str] = Field(default_factory=list)
    approved_by: str | None = None  # user id that resolved it (audit)


class WorkflowEvent(BaseModel):
    """Structured workflow event."""

    event_type: str
    data: dict[str, Any]
    timestamp: str | None = None
    iteration: int | None = None


class ExecutionResult(BaseModel):
    """Result from main execution loop."""

    iterations_completed: int
    success: bool
    final_response: str | None = None
    total_cost: Money = ZERO


class ContinueAsNewState(BaseModel):
    """State carried across continue-as-new boundaries."""

    execution_id: str
    agent_id: str
    task_id: str
    user_id: str
    workspace_id: str
    goal: AgentGoal
    messages: list[dict[str, Any]]  # Already compacted
    agent_config: dict[str, Any]
    available_tools: list[dict[str, Any]]
    current_iteration: int
    tool_calls_used: int = 0
    total_cost: Money = ZERO
    # Child workflow spend included in total_cost. Kept separately so billing
    # can sum each task's own model spend exactly once.
    delegated_cost: Money = ZERO
    tokens_used: int = 0
    budget_usd: Money | None = None
    # Optional only when decoding pre-change Temporal histories. New runs set it
    # from the persisted ModelSpec before context management starts.
    context_window: int | None = None
    user_context_data: dict[str, Any] = Field(default_factory=dict)
    continued_from_run_id: str | None = None
    agent_tool_registry: dict[str, dict[str, Any]] = Field(default_factory=dict)
    activated_skills: list[str] = Field(default_factory=list)
    # Dynamic context discovery
    context_strategy: str = "hybrid"
    history_chunk_counter: int = 0
    activated_tool_sources: list[str] = Field(default_factory=list)
    # Searchable OpenAPI pool: ToolCandidate-shaped dicts (name, description,
    # connection_id, schema, source_type) deferred behind `load_tools`.
    searchable_tool_pool: list[dict[str, Any]] = Field(default_factory=list)
    # Names from the pool already revealed into available_tools — re-applied on replay
    # so prior tool_calls keep resolving after continue-as-new.
    revealed_openapi_tools: list[str] = Field(default_factory=list)
    # Service budget (wallet payments)
    service_budget_usd: Money | None = None
    service_cost_used: Money = ZERO
    wallet_id: str | None = None
    # Cached model resolution — preserved across continue-as-new
    resolved_model: dict | None = None
    effective_policy: dict[str, Any] | None = None
    # Signal/update state must survive Temporal history rollover verbatim.
    message_queue: list[dict[str, Any]] = Field(default_factory=list)
    pending_escalations: dict[str, PendingEscalation] = Field(default_factory=dict)
    pending_input_requests: dict[str, dict[str, Any]] = Field(default_factory=dict)
    a2ui_action_queue: list[dict[str, Any]] = Field(default_factory=list)
    awaiting_input: bool = False
    paused: bool = False
    pause_reason: str = ""
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)
    completion_event_published: bool = False
    waiting_for_continuation: bool = False
    continuation_failure_reason: str | None = None
    continuation_message: str | None = None
    continuation_count: int = 0
    status: str = "executing"
    success: bool = False
    final_response: str | None = None
    failure_reason: str | None = None
    error_message: str | None = None
    blocked_reason: str | None = None
    validation_state: str = "pending"
    validation_repair_attempts: int = 0
    validation_terminal: bool = False


class AgentExecutionState(BaseModel):
    """Simplified execution state with direct attribute access."""

    execution_id: str = ""
    agent_id: str = ""
    task_id: str = ""
    user_id: str = ""
    workspace_id: str = ""  # Add workspace_id for proper multi-tenancy
    goal: AgentGoal | None = None
    status: str = "initializing"  # Will be set to ExecutionStatus.INITIALIZING in workflow
    current_iteration: int = 0
    tool_calls_used: int = 0
    messages: list[Message] = Field(default_factory=list)
    agent_config: dict[str, Any] = Field(default_factory=dict)
    available_tools: list[dict[str, Any]] = Field(default_factory=list)
    final_response: str | None = None
    success: bool = False
    failure_reason: str | None = None
    error_message: str | None = None
    blocked_reason: str | None = None
    validation_state: str = "pending"
    validation_repair_attempts: int = 0
    validation_terminal: bool = False
    budget_usd: Money | None = None
    tokens_used: int = 0  # Cumulative tokens consumed across the run (governance)
    context_window: int | None = None  # Loaded from ModelSpec before the first LLM call
    user_context_data: dict[str, Any] = Field(default_factory=dict)
    activated_skills: list[str] = Field(default_factory=list)
    # Dynamic context discovery
    context_strategy: str = "hybrid"
    history_chunk_counter: int = 0
    activated_tool_sources: list[str] = Field(default_factory=list)
    # Searchable OpenAPI pool: ToolCandidate-shaped dicts kept in workflow state
    # only — never sent to the LLM directly. Catalog text + `load_tools` meta-tool
    # mediate access (issue #115).
    searchable_tool_pool: list[dict[str, Any]] = Field(default_factory=list)
    # Names from the pool whose full schemas have been appended to
    # `available_tools`; tracked so continue-as-new can re-reveal on replay.
    revealed_openapi_tools: list[str] = Field(default_factory=list)
    # Service budget (wallet payments)
    service_budget_usd: Money | None = None
    service_cost_used: Money = ZERO
    wallet_id: str | None = None
    # Cached model resolution — resolved once at workflow start
    resolved_model: dict | None = None
    effective_policy: dict[str, Any] | None = None
