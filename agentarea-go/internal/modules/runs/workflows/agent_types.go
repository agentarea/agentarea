package workflows

import (
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/domain"
)

// AgentRunRequest starts AgentExecutionWorkflow (AgentExecutionRequest).
type AgentRunRequest struct {
	TaskID                string                 `json:"task_id"`
	AgentID               string                 `json:"agent_id"`
	UserID                string                 `json:"user_id"`
	WorkspaceID           string                 `json:"workspace_id"`
	TaskQuery             string                 `json:"task_query"`
	TaskParameters        map[string]any         `json:"task_parameters"`
	RequiresHumanApproval bool                   `json:"requires_human_approval"`
	Budget                *money.Decimal         `json:"budget_usd"`
	WorkflowMetadata      map[string]any         `json:"workflow_metadata"`
	Policy                api.Policy             `json:"effective_policy"`
	Governance            api.GovernanceSnapshot `json:"governance_snapshot"`
	Selections            RunSelections          `json:"selections"`
	Resume                *RunResume             `json:"resume"`
	Continued             *ContinuedState        `json:"continued_state"`
}

// RunResume continues a closed conversation (AgentExecutionResume).
type RunResume struct {
	Snapshot            ResumeSnapshot `json:"snapshot"`
	TotalCost           money.Decimal  `json:"total_cost"`
	OwnCost             *money.Decimal `json:"own_cost"`
	LLMCost             money.Decimal  `json:"llm_cost"`
	SystemPromptMissing bool           `json:"system_prompt_missing"`
	Retry               bool           `json:"retry"`
}

// AgentRunResult is the workflow's result (AgentExecutionResult).
type AgentRunResult struct {
	TaskID              string        `json:"task_id"`
	AgentID             string        `json:"agent_id"`
	Success             bool          `json:"success"`
	Status              string        `json:"status"`
	ValidationState     string        `json:"validation_state"`
	FinalResponse       string        `json:"final_response"`
	ReasoningIterations int           `json:"reasoning_iterations_used"`
	TotalToolCalls      int           `json:"total_tool_calls"`
	TotalCost           money.Decimal `json:"total_cost"`
	FailureReason       string        `json:"failure_reason"`
	ErrorMessage        string        `json:"error_message"`
}

// Goal is the run's task (AgentGoal).
type Goal struct {
	ID                    string         `json:"id"`
	Description           string         `json:"description"`
	SuccessCriteria       []string       `json:"success_criteria"`
	MaxIterations         int            `json:"max_iterations"`
	RequiresHumanApproval bool           `json:"requires_human_approval"`
	Context               map[string]any `json:"context"`
}

// Escalation is a tool call waiting for a human decision (PendingEscalation).
type Escalation struct {
	EscalationID string         `json:"escalation_id"`
	ToolCallID   string         `json:"tool_call_id"`
	ToolName     string         `json:"tool_name"`
	ToolArgs     map[string]any `json:"tool_args"`
	Resolved     bool           `json:"resolved"`
	Approved     bool           `json:"approved"`
	Comment      string         `json:"comment"`
	DenyComment  string         `json:"deny_comment"`
	Approvers    []string       `json:"approvers"`
	ApprovedBy   string         `json:"approved_by"`
}

// InputRequest is a pending request_user_input form.
type InputRequest struct {
	Questions           []map[string]any `json:"questions"`
	SurfaceID           string           `json:"surface_id"`
	AllowCustomResponse bool             `json:"allow_custom_response"`
	Resolved            bool             `json:"resolved"`
	Submission          map[string]any   `json:"submission"`
}

// QueuedMessage is a follow-up waiting for the next model call.
type QueuedMessage struct {
	ID      string            `json:"id"`
	Content string            `json:"content"`
	Sender  map[string]string `json:"sender,omitempty"`
}

// ContinuedState is everything a run carries across continue-as-new (ContinueAsNewState).
type ContinuedState struct {
	ExecutionID          string                         `json:"execution_id"`
	Goal                 Goal                           `json:"goal"`
	Config               api.RunConfig                  `json:"config"`
	Messages             []Message                      `json:"messages"`
	NextSeq              int64                          `json:"conversation_next_seq"`
	LastPromptTokens     int64                          `json:"last_prompt_tokens"`
	SeenURLs             []string                       `json:"seen_urls"`
	TruncatedReply       string                         `json:"truncated_reply"`
	Tools                []api.ToolDefinition           `json:"available_tools"`
	Iteration            int                            `json:"current_iteration"`
	ToolCallsUsed        int                            `json:"tool_calls_used"`
	TotalCost            money.Decimal                  `json:"total_cost"`
	DelegatedCost        money.Decimal                  `json:"delegated_cost"`
	TokensUsed           int64                          `json:"tokens_used"`
	Budget               money.Decimal                  `json:"budget_usd"`
	ContinuedFromRunID   string                         `json:"continued_from_run_id"`
	ActivatedSkills      []string                       `json:"activated_skills"`
	SkillTokensUsed      int                            `json:"skill_tokens_used"`
	ChainExpiresAt       *time.Time                     `json:"chain_expires_at"`
	RunStartedAt         *time.Time                     `json:"run_started_at"`
	HistoryChunkCounter  int                            `json:"history_chunk_counter"`
	ActivatedSources     []string                       `json:"activated_tool_sources"`
	RevealedTools        []string                       `json:"revealed_openapi_tools"`
	ServiceCostUsed      money.Decimal                  `json:"service_cost_used"`
	LLMCostUsed          money.Decimal                  `json:"llm_cost_used"`
	MessageQueue         []QueuedMessage                `json:"message_queue"`
	Escalations          map[string]*Escalation         `json:"pending_escalations"`
	InputRequests        map[string]*InputRequest       `json:"pending_input_requests"`
	A2UIQueue            []map[string]any               `json:"a2ui_action_queue"`
	Interaction          domain.InteractionCapabilities `json:"interaction_capabilities"`
	A2UISurfaces         map[string]map[string]string   `json:"a2ui_surfaces"`
	AwaitingInput        bool                           `json:"awaiting_input"`
	Paused               bool                           `json:"paused"`
	PauseReason          string                         `json:"pause_reason"`
	WorkflowMetadata     map[string]any                 `json:"workflow_metadata"`
	CompletionPublished  bool                           `json:"completion_event_published"`
	WaitingContinuation  bool                           `json:"waiting_for_continuation"`
	ContinuationReason   string                         `json:"continuation_failure_reason"`
	ContinuationMessage  string                         `json:"continuation_message"`
	ContinuationCount    int                            `json:"continuation_count"`
	Status               string                         `json:"status"`
	Success              bool                           `json:"success"`
	FinalResponse        string                         `json:"final_response"`
	FailureReason        string                         `json:"failure_reason"`
	ErrorMessage         string                         `json:"error_message"`
	BlockedReason        string                         `json:"blocked_reason"`
	ValidationState      string                         `json:"validation_state"`
	ValidationRepairs    int                            `json:"validation_repair_attempts"`
	ValidationTerminal   bool                           `json:"validation_terminal"`
	PendingEvents        []Event                        `json:"pending_events"`
	BudgetWarningSent    bool                           `json:"budget_warning_sent"`
	Currency             string                         `json:"currency"`
	ContextWarningSent   bool                           `json:"context_warning_sent"`
	CompactionCount      int                            `json:"compaction_count"`
	ConversationSeeded   bool                           `json:"conversation_seeded"`
	MonthlyCapMessage    string                         `json:"monthly_cap_message"`
	RecordedTurnCalls    []ToolCall                     `json:"recorded_turn_calls"`
	RecordedTurnAnswered []string                       `json:"recorded_turn_answered"`
}

// Execution statuses of the run.
const (
	StatusInitializing           = "initializing"
	StatusExecuting              = "executing"
	StatusWaitingForApproval     = "waiting_for_approval"
	StatusWaitingForInput        = "waiting_for_input"
	StatusWaitingForContinuation = "waiting_for_continuation"
	StatusWaitingForInfra        = "waiting_for_infrastructure"
	StatusBlocked                = "blocked"
	StatusCompleted              = "completed"
	StatusFailed                 = "failed"
	StatusCancelled              = "cancelled"
)
