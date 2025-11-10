"""Domain models for agent execution workflows.

Integrates with existing AgentArea domain models and uses proper UUID types.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentExecutionRequest(BaseModel):
    """Request to execute an agent task via Temporal workflow."""

    # Core identification
    task_id: UUID
    agent_id: UUID
    user_id: str
    workspace_id: str  # Required for proper multi-tenancy

    # Task content
    task_query: str
    task_parameters: dict[str, Any] = Field(default_factory=dict)

    # Execution configuration
    timeout_seconds: int = 300
    max_reasoning_iterations: int = 10
    enable_agent_communication: bool = False
    requires_human_approval: bool = False
    budget_usd: float | None = None  # Optional budget limit in USD

    # Additional workflow metadata
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionResult(BaseModel):
    """Result of agent execution workflow."""

    # Core identification
    task_id: UUID
    agent_id: UUID

    # Execution results
    success: bool
    final_response: str | None = None
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)

    # Performance metrics
    reasoning_iterations_used: int = 0
    total_tool_calls: int = 0
    execution_duration_seconds: float | None = None
    total_cost: float = 0.0

    # Error handling
    error_message: str | None = None

    # Artifacts and outputs
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    agent_memory_updates: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionRequest(BaseModel):
    """Request to execute a tool via MCP server."""

    # Tool identification
    tool_name: str
    tool_server_id: UUID  # MCP server instance ID

    # Tool parameters
    arguments: dict[str, Any]

    # Execution context
    agent_id: UUID
    task_id: UUID
    user_id: str

    # Timeout configuration
    timeout_seconds: int = 60


class ToolExecutionResult(BaseModel):
    """Result of tool execution."""

    # Core identification
    tool_name: str
    tool_server_id: UUID

    # Execution results
    success: bool
    output: str | None = None
    error_message: str | None = None

    # Metadata
    execution_time_seconds: float | None = None
    server_metadata: dict[str, Any] = Field(default_factory=dict)


class LLMReasoningRequest(BaseModel):
    """Request for LLM reasoning and tool selection."""

    # Agent context
    agent_id: UUID
    task_id: UUID

    # Conversation context
    conversation_history: list[dict[str, Any]]
    current_goal: str

    # Available tools
    available_tools: list[dict[str, Any]]

    # Reasoning constraints
    max_tool_calls: int = 5
    include_thinking: bool = True


class LLMReasoningResult(BaseModel):
    """Result of LLM reasoning."""

    # Core response
    reasoning_text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)

    # Metadata
    model_used: str
    reasoning_time_seconds: float | None = None

    # Completion indicators
    believes_task_complete: bool = False
    completion_confidence: float = 0.0


# === Activity Input/Output Models ===


class AgentConfigRequest(BaseModel):
    """Request for building agent configuration."""

    agent_id: UUID
    user_context_data: dict[str, Any]
    execution_context: dict[str, Any] | None = None
    step_type: str | None = None
    override_model: str | None = None


class AgentConfigResult(BaseModel):
    """Agent configuration result."""

    id: str
    name: str
    description: str
    instruction: str
    model_id: str
    tools_config: dict[str, Any] = Field(default_factory=dict)
    events_config: dict[str, Any] = Field(default_factory=dict)
    planning: bool = False
    execution_context: dict[str, Any] | None = None
    step_type: str | None = None


class ToolDiscoveryRequest(BaseModel):
    """Request for discovering available tools."""

    agent_id: UUID
    user_context_data: dict[str, Any]


class ToolDefinition(BaseModel):
    """OpenAI-compatible tool definition."""

    type: str = "function"
    function: dict[str, Any]


class ToolDiscoveryResult(BaseModel):
    """Tools discovery result."""

    tools: list[ToolDefinition]


class LLMCallRequest(BaseModel):
    """Request for LLM call."""

    messages: list[dict[str, Any]]
    model_id: str
    tools: list[dict[str, Any]] | None = None
    workspace_id: str | None = None
    user_context_data: dict[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    task_id: str | None = None
    agent_id: str | None = None
    execution_id: str | None = None


class LLMUsage(BaseModel):
    """LLM usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMCallResult(BaseModel):
    """LLM call result."""

    role: str = "assistant"
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    cost: float = 0.0
    usage: LLMUsage | None = None


class MCPToolRequest(BaseModel):
    """Request for MCP tool execution."""

    tool_name: str
    tool_args: dict[str, Any]
    server_instance_id: UUID | None = None
    workspace_id: str  # Required - must be provided explicitly
    tools_config: dict[str, Any] | None = None


class MCPToolResult(BaseModel):
    """MCP tool execution result."""

    success: bool = True
    result: str = ""
    execution_time: str = ""
    error: str | None = None


class ExecutionPlanRequest(BaseModel):
    """Request for creating execution plan."""

    goal: dict[str, Any]
    available_tools: list[dict[str, Any]]
    messages: list[dict[str, Any]]


class ExecutionPlanResult(BaseModel):
    """Execution plan result."""

    plan: str
    estimated_steps: int
    key_tools: list[str]
    risk_factors: list[str]


class GoalEvaluationRequest(BaseModel):
    """Request for goal progress evaluation."""

    goal: dict[str, Any]
    messages: list[dict[str, Any]]
    current_iteration: int


class GoalEvaluationResult(BaseModel):
    """Goal evaluation result."""

    goal_achieved: bool = False
    confidence: float = 0.0
    final_response: str | None = None
    reasoning: str = ""
    next_steps: list[str] = Field(default_factory=list)


class WorkflowEventsRequest(BaseModel):
    """Request for publishing workflow events."""

    events_json: list[str]
    workspace_id: str  # Required - from workflow state
    user_id: str  # Required - from workflow state


class WorkflowEventsResult(BaseModel):
    """Workflow events publishing result."""

    success: bool
    events_published: int
    errors: list[str] = Field(default_factory=list)


# === Trigger Activity Models ===


class ExecuteTriggerRequest(BaseModel):
    """Request to execute a trigger."""

    trigger_id: UUID
    execution_data: dict[str, Any] = Field(default_factory=dict)


class ExecuteTriggerResult(BaseModel):
    """Trigger execution result."""

    trigger_id: UUID
    status: str
    task_id: UUID | None = None
    execution_id: UUID | None = None
    execution_time_ms: int = 0
    reason: str | None = None
    trigger_data: dict[str, Any] = Field(default_factory=dict)


class RecordTriggerExecutionRequest(BaseModel):
    """Request to record trigger execution."""

    trigger_id: UUID
    execution_data: dict[str, Any]


class RecordTriggerExecutionResult(BaseModel):
    """Record trigger execution result."""

    execution_id: UUID
    trigger_id: UUID
    status: str
    recorded_at: str


class EvaluateTriggerConditionsRequest(BaseModel):
    """Request to evaluate trigger conditions."""

    trigger_id: UUID
    event_data: dict[str, Any] = Field(default_factory=dict)


class EvaluateTriggerConditionsResult(BaseModel):
    """Trigger conditions evaluation result."""

    conditions_met: bool = False
    trigger_id: UUID | None = None


class CreateTaskFromTriggerRequest(BaseModel):
    """Request to create task from trigger."""

    trigger_id: UUID
    execution_data: dict[str, Any] = Field(default_factory=dict)


class CreateTaskFromTriggerResult(BaseModel):
    """Create task from trigger result."""

    task_id: UUID | None = None
    trigger_id: UUID
    status: str
    task_parameters: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
