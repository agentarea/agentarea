"""Domain models for agent execution workflows.

Integrates with existing AgentArea domain models and uses proper UUID types.
"""

from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from agentarea_common.money import ZERO, Money
from pydantic import BaseModel, Field, model_validator


class ResolvedModelInfo(BaseModel):
    """Cached model resolution info stored in workflow state.

    api_key_secret is the SECRET MANAGER KEY NAME (e.g. "provider_123_api_key"),
    NOT the actual API key. The actual key is decrypted inside activities only.
    """

    model_id: str
    provider_type: str
    model_name: str
    api_key_secret: str | None = None  # secret manager key name, not the actual key
    endpoint_url: str | None = None
    context_window: int = Field(gt=0)
    max_output_tokens: int | None = Field(
        default=None,
        gt=0,
    )  # model_spec cap; bounds the per-call max_tokens
    input_cost_per_token: float | None = Field(default=None, ge=0)
    output_cost_per_token: float | None = Field(default=None, ge=0)
    display_name: str | None = None
    provider_display_name: str | None = None
    resolved_at: str | None = None  # ISO timestamp for staleness debugging


class ResolveModelRequest(BaseModel):
    """Request to resolve model info for caching."""

    model_id: str
    workspace_id: str
    user_id: str | None = None


class WorkflowCommand(BaseModel):
    """Generic workflow command sent via signal."""

    command: str  # "change_model", "update_budget", etc.
    payload: dict[str, Any]


class ChangeModelPayload(BaseModel):
    """Typed payload for change_model command."""

    model_id: str
    provider_type: str
    model_name: str
    api_key_secret: str | None = None
    endpoint_url: str | None = None
    context_window: int = Field(gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    input_cost_per_token: float | None = Field(default=None, ge=0)
    output_cost_per_token: float | None = Field(default=None, ge=0)
    display_name: str | None = None
    provider_display_name: str | None = None
    resolved_at: str | None = None


class BudgetUpdatePayload(BaseModel):
    """Validated absolute inference-budget update."""

    budget_usd: Money = Field(gt=ZERO)


class ContinueExecutionPayload(BaseModel):
    """Additional resources granted to a workflow waiting on a limit."""

    additional_iterations: int = Field(default=0, ge=0, le=1000)
    additional_budget_usd: Money | None = Field(default=None, gt=ZERO)
    effective_policy: dict[str, Any] | None = None
    governance_snapshot: dict[str, Any] | None = None


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
    timeout_seconds: int | None = None
    # Legacy input kept for Temporal history compatibility. New workflow runs
    # derive their model-turn ceiling exclusively from effective_policy.
    max_reasoning_iterations: int | None = None
    requires_human_approval: bool = False
    budget_usd: Money | None = None  # Optional budget limit in USD

    # Additional workflow metadata
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)
    effective_policy: dict[str, Any] | None = None

    # Continue-as-new state (populated when workflow restarts with fresh event history)
    continued_state: dict[str, Any] | None = None


class AgentExecutionResult(BaseModel):
    """Result of agent execution workflow."""

    # Core identification
    task_id: UUID
    agent_id: UUID

    # Execution results
    success: bool
    status: str | None = None
    validation_state: str | None = None
    final_response: str | None = None
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)

    # Performance metrics
    reasoning_iterations_used: int = 0
    total_tool_calls: int = 0
    execution_duration_seconds: float | None = None
    total_cost: Money = ZERO

    # Error handling
    failure_reason: str | None = None
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


class SkillInfo(BaseModel):
    """Skill information for execution context."""

    id: str
    name: str
    description: str = ""  # For catalog display (progressive disclosure)
    content: str  # Markdown body
    files: list[str] = Field(default_factory=list)  # Available file paths


class RuntimePython(BaseModel):
    version: str
    executable: str


class RuntimeNode(BaseModel):
    version: str
    npm_version: str


class RuntimeFeatures(BaseModel):
    browser: Literal["none", "playwright"]
    managed_environment_mutation: bool
    arbitrary_workspace_code: bool


class RuntimeExecutionSupervisor(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_version: Literal[1]
    command_uid: int = Field(gt=0)
    command_gid: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_path(self) -> "RuntimeExecutionSupervisor":
        parsed = PurePosixPath(self.path)
        if not parsed.is_absolute() or str(parsed) != self.path or self.path == "/":
            raise ValueError("execution supervisor path must be an absolute clean file path")
        return self


class RuntimeManifest(BaseModel):
    schema_version: Literal[2]
    image_version: str
    managed_environment: Literal["mutable", "immutable"]
    python: RuntimePython
    node: RuntimeNode
    tools: dict[str, str] = Field(default_factory=dict)
    packages: dict[str, str] = Field(default_factory=dict)
    features: RuntimeFeatures
    execution_supervisor: RuntimeExecutionSupervisor

    @model_validator(mode="after")
    def validate_profile_features(self) -> "RuntimeManifest":
        expected_mutation = self.managed_environment == "mutable"
        if self.features.managed_environment_mutation != expected_mutation:
            raise ValueError("managed environment feature disagrees with profile")
        if not self.features.arbitrary_workspace_code:
            raise ValueError("runtime must disclose arbitrary workspace code capability")
        return self


class RuntimeDiscoveryResult(BaseModel):
    manifest: RuntimeManifest | None = None
    error: str | None = None


class CapabilityUnavailableResult(BaseModel):
    status: Literal["blocked"] = "blocked"
    reason: Literal["capability_unavailable"] = "capability_unavailable"
    capability: str
    runtime_version: str | None = None


class ArtifactValidationIssue(BaseModel):
    """One actionable failure produced by the runtime artifact validator."""

    path: str
    validator: str
    code: str
    message: str


class ArtifactValidationEvidence(BaseModel):
    """Identity-only evidence for an artifact checked in the task workspace."""

    path: str
    validator: str
    sha256: str
    size: int


class ArtifactValidationRequest(BaseModel):
    """Request to persist and verify the files a completion claims to deliver."""

    workspace_id: str
    task_id: str
    workflow_id: str
    declared_paths: list[str] = Field(default_factory=list, max_length=1000)


class ArtifactValidationResult(BaseModel):
    """Fail-closed outcome returned by the validation activity."""

    state: Literal["passed", "failed", "unavailable"]
    generation: int
    evidence: list[ArtifactValidationEvidence] = Field(default_factory=list)
    issues: list[ArtifactValidationIssue] = Field(default_factory=list)
    capability_unavailable: CapabilityUnavailableResult | None = None


class AgentConfigResult(BaseModel):
    """Agent configuration result."""

    id: str
    name: str
    description: str
    instruction: str
    agent_type: str = "stateless"
    model_id: str
    context_window: int = Field(gt=0)  # From ModelSpec, used for context window management
    default_context_strategy: str | None = None  # From ModelSpec: "static", "hybrid", "dynamic"
    tools: list[dict[str, Any]] = Field(default_factory=list)
    events_config: dict[str, Any] = Field(default_factory=dict)
    planning: bool = False
    a2ui_enabled: bool = False
    execution_context: dict[str, Any] | None = None
    step_type: str | None = None
    skills: list[SkillInfo] = Field(default_factory=list)
    runtime: RuntimeDiscoveryResult | None = None
    runtime_event_data: dict[str, Any] = Field(default_factory=dict)


class ToolDiscoveryRequest(BaseModel):
    """Request for discovering available tools."""

    agent_id: UUID
    user_context_data: dict[str, Any]


class ToolDefinition(BaseModel):
    """OpenAI-compatible tool definition."""

    type: str = "function"
    function: dict[str, Any]


class SearchableToolEntry(BaseModel):
    """Deferred tool entry — used by the disclosure layer for `load_tools`.

    Carries enough metadata for the catalog block (name + description) and
    for on-demand reveal (full schema + connection_id). Lives in workflow
    state until revealed; never sent to the LLM directly.

    Note: `schema_` is aliased to JSON key `"schema"` because Pydantic's
    BaseModel reserves `schema` on the class. Callers MUST use
    `model_dump(by_alias=True)` to round-trip through the workflow's
    `searchable_tool_pool` (plain dicts) — otherwise the dict key becomes
    `schema_` and `ToolCandidate(**c)` reconstruction will silently miss it.
    """

    name: str
    description: str = ""
    connection_id: str = ""
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    source_type: str = "openapi"

    model_config = {"populate_by_name": True}


class ToolDiscoveryResult(BaseModel):
    """Tools discovery result.

    `tools` ships in the LLM's available_tools every call (current behavior).
    `searchable_entries` is the deferred pool for the `load_tools` meta-tool;
    schemas land in available_tools only when the LLM explicitly reveals them.
    """

    tools: list[ToolDefinition]
    searchable_entries: list[SearchableToolEntry] = Field(default_factory=list)


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
    iteration: int | None = None  # identifies the streamed chunks of this call
    resolved_model: dict | None = None  # Cached ResolvedModelInfo dict; None = DB lookup
    effective_policy: dict[str, Any] | None = None
    # Runtime governance counters — let budget gates compare against the running total
    cost_used: float | None = None
    tokens_used: int | None = None
    service_cost_used: float | None = None


class LLMUsage(BaseModel):
    """LLM usage statistics."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMCallResult(BaseModel):
    """LLM call result."""

    role: str = "assistant"
    content: str = ""
    thinking: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    cost: Money = ZERO
    usage: LLMUsage | None = None


class MCPToolRequest(BaseModel):
    """Request for MCP tool execution."""

    tool_name: str
    tool_args: dict[str, Any]
    server_instance_id: UUID | None = None
    workspace_id: str  # Required - must be provided explicitly
    user_id: str | None = None  # Authenticated task owner for workspace-scoped code tools
    task_id: str | None = None  # Scopes artifact-style tools to a task
    execution_id: str | None = None
    tool_call_id: str | None = None
    agent_id: UUID | None = None  # Calling agent — used by self-referential tools (e.g. triggers)
    tools: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    effective_policy: dict[str, Any] | None = None
    # Runtime governance counters — let budget gates compare against the running total
    cost_used: float | None = None
    tokens_used: int | None = None
    service_cost_used: float | None = None


class MCPToolResult(BaseModel):
    """MCP tool execution result."""

    success: bool = True
    result: str = ""
    execution_time: str = ""
    error: str | None = None
    # A command's verdict is data, not prose: consumers (UI, rollups) need the
    # exit code as a field, and `success` alone cannot carry it.
    exit_code: int | None = None
    outcome: str | None = None  # "exit" | "timeout" | "error"
    artifact_paths: list[str] = Field(default_factory=list)
    service_cost: float = 0.0
    payment: dict[str, Any] | None = None
    # Tool-call attribution surfaced to the UI.
    source: str | None = None  # "mcp" | "builtin" | "openapi"
    server_instance_id: str | None = None
    server_name: str | None = None
    server_icon: str | None = None


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


class UpdateTaskStatusRequest(BaseModel):
    """Request to update task status in the database."""

    task_id: str
    status: str  # completed, failed, cancelled
    result: str | None = None
    error_message: str | None = None
    workspace_id: str
    total_cost: Money | None = None
    own_cost: Money | None = None


class UpdateTaskStatusResult(BaseModel):
    """Result of task status update."""

    success: bool
    error: str | None = None


class UpdateTaskGovernanceSnapshotRequest(BaseModel):
    """Persist a re-resolved policy before resuming a waiting workflow."""

    task_id: str
    workspace_id: str
    governance_snapshot: dict[str, Any]


class UpdateTaskGovernanceSnapshotResult(BaseModel):
    success: bool
    error: str | None = None


class CompactMessagesRequest(BaseModel):
    """Request to compact/summarize older messages."""

    messages_to_compact: list[dict[str, Any]]
    model_id: str
    workspace_id: str
    user_context_data: dict[str, Any] | None = None
    resolved_model: dict | None = None  # Cached ResolvedModelInfo dict; None = DB lookup
    effective_policy: dict[str, Any] | None = None


class CompactMessagesResult(BaseModel):
    """Result of message compaction."""

    summary: str
    original_message_count: int
    estimated_tokens_saved: int
    # Optional only for decoding activity results recorded before accounting
    # was added. New executions require both fields.
    cost: Money | None = None
    usage: LLMUsage | None = None


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


class CreateDelegationTaskRequest(BaseModel):
    """Request to create a task for agent delegation."""

    parent_agent_id: str
    parent_task_id: str
    target_agent_id: str
    target_agent_name: str
    message: str
    user_id: str
    workspace_id: str
    # Optional only for Temporal history compatibility. New callers always
    # provide it and the activity rejects its absence.
    parent_effective_policy: dict[str, Any] | None = None
    run_budget_usd: Money | None = Field(default=None, gt=ZERO)


class CreateDelegationTaskResult(BaseModel):
    """Result of creating a delegation task."""

    task_id: UUID | None = None
    status: str
    error: str | None = None
    # Optional only so old activity payloads remain decodable during rollout.
    effective_policy: dict[str, Any] | None = None


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


# === Skill File Activity Models ===


class ResolveAgentToolsRequest(BaseModel):
    """Request to resolve agent tool names to agent IDs."""

    agent_names: list[str]
    workspace_id: str
    user_context_data: dict[str, Any] | None = None


class ResolveAgentToolsResult(BaseModel):
    """Result of agent tool resolution. Maps agent names to their IDs."""

    agent_map: dict[str, str] = Field(default_factory=dict)  # name → agent_id


class RecallHistoryRequest(BaseModel):
    """Request to recall context from past task executions.

    Used by the recall_history tool to query the DB event log (tier 2)
    for relevant past context that was compacted out of the working set.
    """

    task_id: UUID
    workspace_id: str
    query: str | None = None  # Optional search query to filter events
    event_types: list[str] | None = None  # Filter by event types
    limit: int = 20
    user_context_data: dict[str, Any] | None = None


class RecallHistoryResult(BaseModel):
    """Result of history recall."""

    events: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    summary: str = ""


class MaterializeSkillFilesRequest(BaseModel):
    """Request to copy a skill's bundle into the task's sandbox workspace."""

    skill_id: UUID
    skill_name: str
    workflow_id: str | None = None
    workspace_id: str | None = None
    task_id: str | None = None


class MaterializeSkillFilesResult(BaseModel):
    """Where a skill's files landed in the sandbox."""

    success: bool = False
    directory: str = ""
    paths: list[str] = Field(default_factory=list)
    error: str | None = None


# === Context Store Activity Models ===


class StoreOutputRequest(BaseModel):
    """Request to store a large tool output in MinIO."""

    task_id: str
    workspace_id: str
    output_id: str
    content: str


class StoreOutputResult(BaseModel):
    """Result of storing a tool output."""

    success: bool
    error: str | None = None


class ReadOutputRequest(BaseModel):
    """Request to read a stored tool output from MinIO."""

    task_id: str
    workspace_id: str
    output_id: str
    grep: str | None = None
    head: int | None = None
    tail: int | None = None


class ReadOutputResult(BaseModel):
    """Result of reading a stored tool output."""

    success: bool
    content: str = ""
    error: str | None = None


class StoreHistoryRequest(BaseModel):
    """Request to store compacted messages in MinIO."""

    task_id: str
    workspace_id: str
    chunk_index: int
    messages: list[dict[str, Any]]


class StoreHistoryResult(BaseModel):
    """Result of storing a history chunk."""

    success: bool
    error: str | None = None


class SearchHistoryRequest(BaseModel):
    """Request to search stored history chunks in MinIO."""

    task_id: str
    workspace_id: str
    grep: str | None = None
    tool_name: str | None = None
    message_type: str | None = None


class SearchHistoryResult(BaseModel):
    """Result of searching history chunks."""

    success: bool
    results: str = ""
    error: str | None = None


class ToolProviderData(BaseModel):
    """Serializable representation of a ToolProvider for workflow transport."""

    name: str
    provider_type: str  # "mcp", "code", "agent", "builtin"
    tool_names: list[str] = Field(default_factory=list)
    description: str = ""
    tools: list[dict[str, Any]] = Field(default_factory=list)


class DiscoverToolProvidersResult(BaseModel):
    """Result from discover_tool_providers activity."""

    providers: list[ToolProviderData] = Field(default_factory=list)
    success: bool = True
    error: str | None = None
