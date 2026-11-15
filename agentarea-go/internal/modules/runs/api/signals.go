package api

import "github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"

// Signals, queries and the update of AgentExecutionWorkflow, by the names the
// Python workflow registered them under.
const (
	SignalPause             = "pause_execution"
	SignalResume            = "resume_execution"
	SignalA2UIAction        = "handle_a2ui_action"
	SignalResolveEscalation = "resolve_escalation"
	SignalRunnerTurnUpdate  = "runner_turn_update"
	SignalWorkflowCommand   = "workflow_command"

	QueryPendingEscalation = "get_pending_escalations"
	QueryCurrentState      = "get_current_state"

	UpdateContinueExecution = "continue_execution"
)

// Commands a workflow_command signal carries.
const (
	CommandChangeModel       = "change_model"
	CommandUpdateBudget      = "update_budget"
	CommandContinueExecution = "continue_execution"
	CommandQueueMessage      = "queue_message"
	CommandSubmitUserInput   = "submit_user_input"
	CommandRemoveMessage     = "remove_message"
)

// PauseSignal and ResumeSignal carry the reason shown in the events.
type PauseSignal struct {
	Reason string `json:"reason"`
}

type ResolveEscalationSignal struct {
	EscalationID string `json:"escalation_id"`
	Approved     bool   `json:"approved"`
	Comment      string `json:"comment"`
	ResolvedBy   string `json:"resolved_by"`
}

// WorkflowCommandSignal is a mid-run command; Payload is the command's JSON object.
type WorkflowCommandSignal struct {
	Command string         `json:"command"`
	Payload map[string]any `json:"payload"`
}

// ContinueExecution grants a run waiting on a limit more resources under a
// re-resolved policy revision.
type ContinueExecution struct {
	AdditionalIterations int                 `json:"additional_iterations"`
	AdditionalBudget     *money.Decimal      `json:"additional_budget_usd"`
	AdditionalTokens     int                 `json:"additional_tokens"`
	AdditionalToolCalls  int                 `json:"additional_tool_calls"`
	Policy               *Policy             `json:"effective_policy"`
	Governance           *GovernanceSnapshot `json:"governance_snapshot"`
}

// ContinueExecutionResult is the update's answer.
type ContinueExecutionResult struct {
	Accepted          bool   `json:"accepted"`
	Reason            string `json:"reason,omitempty"`
	ContinuationCount int    `json:"continuation_count,omitempty"`
	MaxIterations     int    `json:"max_iterations,omitempty"`
	Budget            string `json:"budget_usd,omitempty"`
}

// PendingEscalationView is one unresolved escalation with its exact arguments.
type PendingEscalationView struct {
	EscalationID string         `json:"escalation_id"`
	ToolName     string         `json:"tool_name"`
	ToolCallID   string         `json:"tool_call_id"`
	ToolArgs     map[string]any `json:"tool_args"`
	Approvers    []string       `json:"approvers"`
}
