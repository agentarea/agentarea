package workflows

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// Principal is who an activity acts as: the run's agent in its workspace, for
// the user who started it.
type Principal struct {
	WorkspaceID string `json:"workspace_id"`
	UserID      string `json:"user_id"`
	AgentID     string `json:"agent_id"`
}

// RunSelections are a task's per-run additions to the saved agent.
type RunSelections struct {
	MCPInstanceIDs []string `json:"mcp_instance_ids"`
	SkillIDs       []string `json:"skill_ids"`
	FileIDs        []string `json:"file_ids"`
	ModelOverride  string   `json:"model_override"`
	ProjectID      string   `json:"project_id"`
	// TriggerEvent is the event a trigger started the run with; too large to
	// quote, it is written to TriggerEventFileName instead.
	TriggerEvent         map[string]any `json:"trigger_event"`
	TriggerEventFileName string         `json:"trigger_event_file_name"`
}

type ResolveRunConfigRequest struct {
	Principal  Principal              `json:"principal"`
	TaskID     string                 `json:"task_id"`
	Selections RunSelections          `json:"selections"`
	Policy     api.Policy             `json:"policy"`
	Governance api.GovernanceSnapshot `json:"governance"`
}

// ToolCall is one call the model asked for; Arguments is the model's JSON text.
type ToolCall struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// ImageRef is an image stored with the task's offloaded context, never its bytes.
type ImageRef struct {
	ID       string `json:"id"`
	MimeType string `json:"mime_type"`
	Size     int64  `json:"size"`
	Width    int    `json:"width,omitempty"`
	Height   int    `json:"height,omitempty"`
	// Pages is a PDF's page count; a PDF is sent as a file, not an image.
	Pages int `json:"pages,omitempty"`
}

// Message is a conversation entry not yet in the task log.
type Message struct {
	// Kind is message or compaction.
	Kind        string         `json:"kind"`
	Role        string         `json:"role"`
	Content     string         `json:"content"`
	ToolCalls   []ToolCall     `json:"tool_calls"`
	ToolCallID  string         `json:"tool_call_id"`
	Name        string         `json:"name"`
	Attachments []ImageRef     `json:"attachments"`
	Meta        map[string]any `json:"meta"`
}

// Conversation is where a task's log ends: the model call reads its window
// from the log and writes the request's pending messages at NextSeq.
type Conversation struct {
	TaskID  string `json:"task_id"`
	NextSeq int64  `json:"next_seq"`
}

// Counters are the run's totals so far, for the budget gates.
type Counters struct {
	Cost        money.Decimal `json:"cost"`
	Tokens      int64         `json:"tokens"`
	ServiceCost money.Decimal `json:"service_cost"`
}

type LLMCallRequest struct {
	Principal   Principal `json:"principal"`
	TaskID      string    `json:"task_id"`
	ExecutionID string    `json:"execution_id"`
	Iteration   int       `json:"iteration"`
	// Purpose is turn or answer_check.
	Purpose            string               `json:"purpose"`
	Model              api.ResolvedModel    `json:"model"`
	Conversation       *Conversation        `json:"conversation"`
	Messages           []Message            `json:"messages"`
	Tools              []api.ToolDefinition `json:"tools"`
	Temperature        *float64             `json:"temperature"`
	MaxTokens          *int                 `json:"max_tokens"`
	ReasoningEffort    string               `json:"reasoning_effort"`
	ReasoningMaxTokens *int                 `json:"reasoning_max_tokens"`
	// StreamText false withholds reply text from the chunk stream; thinking still streams.
	StreamText bool       `json:"stream_text"`
	Policy     api.Policy `json:"policy"`
	Counters   Counters   `json:"counters"`
}

// ChargeLine is how a paid model call's spend line settles.
type ChargeLine struct {
	ModelInstanceID string        `json:"model_instance_id"`
	Amount          money.Decimal `json:"amount"`
	Currency        string        `json:"currency"`
	VendorCost      money.Decimal `json:"vendor_cost"`
	VendorCurrency  string        `json:"vendor_currency"`
	Estimate        bool          `json:"estimate"`
	// Settle is capture (the settlement worker captures HoldID) or empty.
	Settle         string `json:"settle"`
	HoldID         string `json:"hold_id"`
	CostUnknown    bool   `json:"cost_unknown"`
	PlatformFunded bool   `json:"platform_funded"`
	Payer          string `json:"payer"`
}

// LLMUsage counts tokens; PromptTokens includes CachedPromptTokens.
type LLMUsage struct {
	PromptTokens        int64       `json:"prompt_tokens"`
	CompletionTokens    int64       `json:"completion_tokens"`
	TotalTokens         int64       `json:"total_tokens"`
	CachedPromptTokens  int64       `json:"cached_prompt_tokens"`
	CacheCreationTokens int64       `json:"cache_creation_tokens"`
	Billing             *ChargeLine `json:"billing"`
}

type LLMCallResult struct {
	Role      string     `json:"role"`
	Content   string     `json:"content"`
	Thinking  string     `json:"thinking"`
	ToolCalls []ToolCall `json:"tool_calls"`
	// Cost is what the customer pays, in Currency; ProviderCostUSD what the provider charged.
	Cost            money.Decimal `json:"cost"`
	ProviderCostUSD money.Decimal `json:"provider_cost_usd"`
	Currency        string        `json:"currency"`
	ManagedBy       string        `json:"managed_by"`
	Usage           LLMUsage      `json:"usage"`
	Interrupted     bool          `json:"interrupted"`
	FinishReason    string        `json:"finish_reason"`
}

type CompactMessagesRequest struct {
	Principal         Principal         `json:"principal"`
	Conversation      Conversation      `json:"conversation"`
	Pending           []Message         `json:"pending"`
	KeepRecent        int               `json:"keep_recent"`
	HistoryChunkIndex *int              `json:"history_chunk_index"`
	Model             api.ResolvedModel `json:"model"`
	Policy            api.Policy        `json:"policy"`
	Counters          Counters          `json:"counters"`
}

// CompactMessagesResult is the summary the run appends as a compaction row;
// OriginalMessageCount 0 means nothing could be compacted.
type CompactMessagesResult struct {
	Summary              string        `json:"summary"`
	Skills               []string      `json:"skills"`
	OriginalMessageCount int           `json:"original_message_count"`
	EstimatedTokensSaved int           `json:"estimated_tokens_saved"`
	ContextTokens        int           `json:"context_tokens"`
	HistoryChunkStored   bool          `json:"history_chunk_stored"`
	Cost                 money.Decimal `json:"cost"`
	Usage                LLMUsage      `json:"usage"`
}

type ToolCallRequest struct {
	Principal   Principal       `json:"principal"`
	TaskID      string          `json:"task_id"`
	ExecutionID string          `json:"execution_id"`
	ToolCallID  string          `json:"tool_call_id"`
	ToolName    string          `json:"tool_name"`
	Args        map[string]any  `json:"args"`
	Binding     api.ToolBinding `json:"binding"`
	Policy      api.Policy      `json:"policy"`
	Counters    Counters        `json:"counters"`
	// RunMetadata is the run's metadata the signed call context carries.
	RunMetadata map[string]any `json:"run_metadata"`
	// EscalationApproved: a person approved this call after a governance escalation.
	EscalationApproved bool `json:"escalation_approved"`
	// PolicyApprovalGranted: the workflow's policy gate approved this call.
	PolicyApprovalGranted bool `json:"policy_approval_granted"`
}

// Payment is one wallet payment a tool call made (x402 or MPP).
type Payment struct {
	Protocol  string        `json:"protocol"`
	Amount    money.Decimal `json:"amount"`
	Currency  string        `json:"currency"`
	Network   string        `json:"network"`
	Reference string        `json:"reference"`
	Settled   bool          `json:"settled"`
}

type ToolCallResult struct {
	Success  bool          `json:"success"`
	Result   string        `json:"result"`
	Duration time.Duration `json:"duration"`
	Error    string        `json:"error"`
	ExitCode *int          `json:"exit_code"`
	// Outcome is exit, timeout or error for commands.
	Outcome       string        `json:"outcome"`
	ArtifactPaths []string      `json:"artifact_paths"`
	ServiceCost   money.Decimal `json:"service_cost"`
	ModelCost     money.Decimal `json:"model_cost"`
	ModelBilling  *ChargeLine   `json:"model_billing"`
	CostUnknown   bool          `json:"cost_unknown"`
	// Cost is the connector's declared cost as metered; CostMetered says the
	// activity already wrote its ledger lines.
	Cost        money.Decimal `json:"cost"`
	Payer       string        `json:"payer"`
	CostMetered bool          `json:"cost_metered"`
	Replayed    bool          `json:"replayed"`
	Attempt     *int          `json:"attempt"`
	Payments    []Payment     `json:"payments"`
	// Source is mcp, builtin, openapi or code.
	Source                   string     `json:"source"`
	ServerInstanceID         string     `json:"server_instance_id"`
	ServerName               string     `json:"server_name"`
	ServerIcon               string     `json:"server_icon"`
	StructuredContent        any        `json:"structured_content"`
	StructuredContentDropped bool       `json:"structured_content_dropped"`
	MCPAppTool               string     `json:"mcp_app_tool"`
	Images                   []ImageRef `json:"images"`
	// RemoteTask is the task a remote delegate still runs; the answer is not known yet.
	RemoteTask *api.RemoteAgentTask `json:"remote_task"`
}

// RemoteTaskRequest reads or stops the task a remote delegate call started.
type RemoteTaskRequest struct {
	Principal   Principal           `json:"principal"`
	TaskID      string              `json:"task_id"`
	ExecutionID string              `json:"execution_id"`
	ToolCallID  string              `json:"tool_call_id"`
	ToolName    string              `json:"tool_name"`
	Binding     api.ToolBinding     `json:"binding"`
	Task        api.RemoteAgentTask `json:"task"`
}

// RemoteDelegationRequest starts RemoteDelegationWorkflow: the call to send, and when to
// stop waiting for its task. State carries a wait into its next run (continue-as-new).
type RemoteDelegationRequest struct {
	Call     ToolCallRequest        `json:"call"`
	Deadline time.Time              `json:"deadline"`
	State    *RemoteDelegationState `json:"state"`
}

// RemoteDelegationState is a wait under way: what the send answered, the task, how often
// it was read (Reads every attempt, Polls those answered, Failures those failed in a row)
// and how long the next pause is.
type RemoteDelegationState struct {
	Sent     ToolCallResult      `json:"sent"`
	Task     api.RemoteAgentTask `json:"task"`
	Started  time.Time           `json:"started"`
	Reads    int                 `json:"reads"`
	Polls    int                 `json:"polls"`
	Failures int                 `json:"failures"`
	Delay    time.Duration       `json:"delay"`
}

// RemoteDelegationResult is the remote delegate's answer and the task it ran ("" for none).
type RemoteDelegationResult struct {
	Answer ToolCallResult `json:"answer"`
	TaskID string         `json:"task_id"`
}

// Event is one run event; its ID is assigned by the workflow and keys every write.
type Event struct {
	ID        string         `json:"id"`
	Type      string         `json:"type"`
	Data      map[string]any `json:"data"`
	Timestamp time.Time      `json:"timestamp"`
	Iteration *int           `json:"iteration"`
}

// LogRow is one task log row at the position and id the workflow gave it.
type LogRow struct {
	Seq     int64  `json:"seq"`
	EventID string `json:"event_id"`
	// Kind is message, compaction or event; an event's type is Name and its data Meta.
	Kind        string         `json:"kind"`
	Role        string         `json:"role"`
	Content     string         `json:"content"`
	ToolCalls   []ToolCall     `json:"tool_calls"`
	ToolCallID  string         `json:"tool_call_id"`
	Name        string         `json:"name"`
	Attachments []ImageRef     `json:"attachments"`
	Meta        map[string]any `json:"meta"`
	Iteration   *int           `json:"iteration"`
	Timestamp   *time.Time     `json:"timestamp"`
}

// ResumeSnapshot is where a closed task's conversation stands, so a later run continues it.
type ResumeSnapshot struct {
	NextSeq          int64 `json:"next_seq"`
	CurrentIteration int   `json:"current_iteration"`
	ToolCallsUsed    int   `json:"tool_calls_used"`
	TokensUsed       int64 `json:"tokens_used"`
	LastPromptTokens int64 `json:"last_prompt_tokens"`
}

// TaskStatus is the task row's status and result as a record call stores them.
type TaskStatus struct {
	Status          string          `json:"status"`
	Response        string          `json:"response"`
	Artifacts       []string        `json:"artifacts"`
	ValidationState string          `json:"validation_state"`
	ErrorMessage    string          `json:"error_message"`
	FailureReason   string          `json:"failure_reason"`
	TotalCost       *money.Decimal  `json:"total_cost"`
	OwnCost         *money.Decimal  `json:"own_cost"`
	TokensUsed      *int64          `json:"tokens_used"`
	Resume          *ResumeSnapshot `json:"resume"`
	RunStartedAt    *time.Time      `json:"run_started_at"`
}

// RecordRequest is what a run records at once: rows, status, and the spend
// and audit lines its event rows stand for in one transaction; then every
// event row is published, and Live (live-only types) is broadcast.
type RecordRequest struct {
	Principal   Principal   `json:"principal"`
	TaskID      string      `json:"task_id"`
	ExecutionID string      `json:"execution_id"`
	Rows        []LogRow    `json:"rows"`
	Live        []Event     `json:"live"`
	Status      *TaskStatus `json:"status"`
	// TurnStart marks the record that starts a follow-up turn.
	TurnStart bool `json:"turn_start,omitempty"`
}

type RecordResult struct {
	Rows   int `json:"rows"`
	Events int `json:"events"`
	// TurnStart echoes the request's. The workflow reloads the agent's config only on a result
	// that carries it, so a history recorded before the reload existed replays without one.
	TurnStart bool `json:"turn_start,omitempty"`
}

type UpdateGovernanceSnapshotRequest struct {
	Principal Principal              `json:"principal"`
	TaskID    string                 `json:"task_id"`
	Snapshot  api.GovernanceSnapshot `json:"snapshot"`
}

// MonthlySpendCapRequest compares month-to-date spend with the caps the run
// started under, or with the caps set now when CurrentCaps.
type MonthlySpendCapRequest struct {
	Principal    Principal      `json:"principal"`
	WorkspaceCap *money.Decimal `json:"workspace_cap"`
	AgentCap     *money.Decimal `json:"agent_cap"`
	LLMCaps      []api.SpendCap `json:"llm_caps"`
	CurrentCaps  bool           `json:"current_caps"`
}

type MonthlySpendCapResult struct {
	Exceeded         bool           `json:"exceeded"`
	MonthToDate      money.Decimal  `json:"month_to_date"`
	Cap              *money.Decimal `json:"cap"`
	Currency         string         `json:"currency"`
	AgentExceeded    bool           `json:"agent_exceeded"`
	AgentMonthToDate *money.Decimal `json:"agent_month_to_date"`
	AgentCap         *money.Decimal `json:"agent_cap"`
	// LLMCapMessage says why a monthly LLM cap refuses the run; empty when none does.
	LLMCapMessage string `json:"llm_cap_message"`
}

type DelegatedSpendRequest struct {
	Principal Principal `json:"principal"`
	TaskID    string    `json:"task_id"`
}

type DelegatedSpendResult struct {
	Spent money.Decimal `json:"spent"`
}

type CreateDelegationTaskRequest struct {
	Principal       Principal      `json:"principal"`
	ParentTaskID    string         `json:"parent_task_id"`
	TargetAgentID   string         `json:"target_agent_id"`
	TargetAgentName string         `json:"target_agent_name"`
	Message         string         `json:"message"`
	ParentPolicy    api.Policy     `json:"parent_policy"`
	RunBudget       *money.Decimal `json:"run_budget"`
	// ExecutionID is the child's workflow id, stored on its task row.
	ExecutionID string `json:"execution_id"`
	// WorkspaceTaskID is the task whose files the child works on, the parent's.
	WorkspaceTaskID string `json:"workspace_task_id,omitempty"`
}

// CreateDelegationTaskResult: Status created with TaskID and the child's
// Policy, or failed with Error (the workflow records delegation.failed).
type CreateDelegationTaskResult struct {
	Status         string     `json:"status"`
	TaskID         string     `json:"task_id"`
	Policy         api.Policy `json:"policy"`
	Error          string     `json:"error"`
	RunnerClientID string     `json:"runner_client_id,omitempty"`
}

type ArtifactValidationRequest struct {
	Principal     Principal `json:"principal"`
	TaskID        string    `json:"task_id"`
	ExecutionID   string    `json:"execution_id"`
	DeclaredPaths []string  `json:"declared_paths"`
}

type ArtifactEvidence struct {
	Path      string `json:"path"`
	Validator string `json:"validator"`
	SHA256    string `json:"sha256"`
	Size      int64  `json:"size"`
}

type ArtifactIssue struct {
	Path      string `json:"path"`
	Validator string `json:"validator"`
	Code      string `json:"code"`
	Message   string `json:"message"`
}

type CapabilityUnavailable struct {
	Capability     string `json:"capability"`
	RuntimeVersion string `json:"runtime_version"`
}

// ArtifactValidationResult fails closed: State is passed, failed or unavailable.
type ArtifactValidationResult struct {
	State                 string                 `json:"state"`
	Generation            int                    `json:"generation"`
	Evidence              []ArtifactEvidence     `json:"evidence"`
	Issues                []ArtifactIssue        `json:"issues"`
	CapabilityUnavailable *CapabilityUnavailable `json:"capability_unavailable"`
}

// ActivateSkillRequest writes the skill's entry at Seq under EventID, both
// reserved by the workflow, so a retry writes it once.
type ActivateSkillRequest struct {
	Principal   Principal `json:"principal"`
	TaskID      string    `json:"task_id"`
	FilesTaskID string    `json:"files_task_id,omitempty"`
	ExecutionID string    `json:"execution_id"`
	ToolCallID  string    `json:"tool_call_id"`
	Skill       api.Skill `json:"skill"`
	Seq         int64     `json:"seq"`
	EventID     string    `json:"event_id"`
	Iteration   *int      `json:"iteration"`
	MaxTokens   int       `json:"max_tokens"`
}

// ActivateSkillResult is the entry's size, never its text.
type ActivateSkillResult struct {
	Chars      int      `json:"chars"`
	EstTokens  int      `json:"est_tokens"`
	Summarized bool     `json:"summarized"`
	URLs       []string `json:"urls"`
}

type RecallHistoryRequest struct {
	Principal  Principal `json:"principal"`
	TaskID     string    `json:"task_id"`
	Query      string    `json:"query"`
	EventTypes []string  `json:"event_types"`
	Limit      int       `json:"limit"`
}

// FeedEvent is a task feed row as recall_history returns it.
type FeedEvent struct {
	Seq       int64          `json:"seq"`
	Type      string         `json:"type"`
	Data      map[string]any `json:"data"`
	Timestamp time.Time      `json:"timestamp"`
}

type RecallHistoryResult struct {
	Events     []FeedEvent `json:"events"`
	TotalCount int         `json:"total_count"`
	Summary    string      `json:"summary"`
}

type StoreOutputRequest struct {
	Principal Principal `json:"principal"`
	TaskID    string    `json:"task_id"`
	OutputID  string    `json:"output_id"`
	Content   string    `json:"content"`
}

type ReadOutputRequest struct {
	Principal Principal `json:"principal"`
	TaskID    string    `json:"task_id"`
	// FilesTaskID is the task whose files the run works on, when not its own.
	FilesTaskID string `json:"files_task_id,omitempty"`
	OutputID    string `json:"output_id"`
	Grep        string `json:"grep"`
	Head        *int   `json:"head"`
	Tail        *int   `json:"tail"`
}

type SearchHistoryRequest struct {
	Principal   Principal `json:"principal"`
	TaskID      string    `json:"task_id"`
	Grep        string    `json:"grep"`
	ToolName    string    `json:"tool_name"`
	MessageType string    `json:"message_type"`
}

// ContextResult is the answer of the three context store activities, which
// report failure in Error rather than failing.
type ContextResult struct {
	Success bool   `json:"success"`
	Content string `json:"content"`
	Error   string `json:"error"`
}

// RunnerActor is who a runner's turn acts for: a user or the agent itself.
type RunnerActor struct {
	Type string `json:"type"`
	ID   string `json:"id"`
}

type RunnerTurnRequest struct {
	TaskID      string       `json:"task_id"`
	AgentID     string       `json:"agent_id"`
	WorkspaceID string       `json:"workspace_id"`
	Iteration   int          `json:"iteration"`
	TurnKey     string       `json:"turn_key"`
	Message     string       `json:"message"`
	Actor       *RunnerActor `json:"actor"`
}

// RunnerTurnResult: Status is completed, failed or interrupted.
type RunnerTurnResult struct {
	Status   string `json:"status"`
	Response string `json:"response"`
	Error    string `json:"error"`
}

// RunnerTurnEvent is something the CLI did in a turn; Kind is message, tool.call or tool.result.
type RunnerTurnEvent struct {
	Seq       int64          `json:"seq"`
	Kind      string         `json:"kind"`
	ItemID    string         `json:"item_id"`
	Name      string         `json:"name"`
	Text      string         `json:"text"`
	Model     string         `json:"model"`
	Arguments map[string]any `json:"arguments"`
	Output    string         `json:"output"`
	Success   *bool          `json:"success"`
	ExitCode  *int           `json:"exit_code"`
}

type RunnerApprovalAsk struct {
	RequestID string         `json:"request_id"`
	ItemID    string         `json:"item_id"`
	Kind      string         `json:"kind"`
	ToolName  string         `json:"tool_name"`
	Arguments map[string]any `json:"arguments"`
	Reason    string         `json:"reason"`
}

type RunnerSteerOutcome struct {
	MessageID string `json:"message_id"`
	Accepted  bool   `json:"accepted"`
}

// RunnerTurnUpdate is the runner_turn_update signal run_runner_turn_activity sends its run.
type RunnerTurnUpdate struct {
	TurnKey   string               `json:"turn_key"`
	Actor     *RunnerActor         `json:"actor"`
	Events    []RunnerTurnEvent    `json:"events"`
	Approvals []RunnerApprovalAsk  `json:"approvals"`
	Steers    []RunnerSteerOutcome `json:"steers"`
}

// DeliverToRunnerRequest: Kind is steer (MessageID, Text), decision
// (RequestID, Approved) or pause.
type DeliverToRunnerRequest struct {
	ClientID  string `json:"client_id"`
	TaskID    string `json:"task_id"`
	TurnKey   string `json:"turn_key"`
	Kind      string `json:"kind"`
	MessageID string `json:"message_id"`
	Text      string `json:"text"`
	RequestID string `json:"request_id"`
	Approved  *bool  `json:"approved"`
}

// StartUndispatchedResult is how many tasks with no workflow were started.
type StartUndispatchedResult struct {
	Started int `json:"started"`
}

type EvaluateTriggerConditionsRequest struct {
	TriggerID string         `json:"trigger_id"`
	EventData map[string]any `json:"event_data"`
}

type EvaluateTriggerConditionsResult struct {
	TriggerID     string `json:"trigger_id"`
	ConditionsMet bool   `json:"conditions_met"`
}

type ExecuteTriggerRequest struct {
	TriggerID     string         `json:"trigger_id"`
	ExecutionData map[string]any `json:"execution_data"`
}

// ExecuteTriggerResult: Status is success (a task was made), failed or
// skipped; Reason is trigger_inactive, conditions_not_met, no_new_data or
// previous_run_active for skipped.
type ExecuteTriggerResult struct {
	TriggerID   string         `json:"trigger_id"`
	Status      string         `json:"status"`
	TaskID      string         `json:"task_id"`
	ExecutionID string         `json:"execution_id"`
	Duration    time.Duration  `json:"duration"`
	Reason      string         `json:"reason"`
	Error       string         `json:"error"`
	TriggerData map[string]any `json:"trigger_data"`
}

type RecordTriggerExecutionRequest struct {
	TriggerID     string         `json:"trigger_id"`
	ExecutionData map[string]any `json:"execution_data"`
}

type RecordTriggerExecutionResult struct {
	ExecutionID string    `json:"execution_id"`
	TriggerID   string    `json:"trigger_id"`
	Status      string    `json:"status"`
	RecordedAt  time.Time `json:"recorded_at"`
}

// BatchSpec is what a trigger batch fires and when, fixed for the run that holds it.
type BatchSpec struct {
	TriggerID      string        `json:"trigger_id"`
	SubscriptionID string        `json:"subscription_id"`
	WorkspaceID    string        `json:"workspace_id"`
	ConfiguredBy   string        `json:"configured_by"`
	Caller         string        `json:"caller"`
	Window         time.Duration `json:"window"`
	MaxEvents      int           `json:"max_events"`
	Pending        []string      `json:"pending"`
}

// OpenBatch is the input of fire and close; both return how many events they handled.
type OpenBatch struct {
	Spec       BatchSpec `json:"spec"`
	WorkflowID string    `json:"workflow_id"`
	EventIDs   []string  `json:"event_ids"`
	Reason     string    `json:"reason"`
}

type BatchResult struct {
	Events int `json:"events"`
}
