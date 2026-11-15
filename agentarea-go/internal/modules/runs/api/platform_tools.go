package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// RunStart is runs_start's arguments (RunCreate).
type RunStart struct {
	AgentID               string
	Description           string
	Parameters            map[string]any
	RequiresHumanApproval bool
	ProjectID             *string
	ScheduledAt           *string
}

// RunStarted is runs_start's output.
type RunStarted struct {
	RunID       string  `json:"run_id"`
	Status      string  `json:"status"`
	ScheduledAt *string `json:"scheduled_at"`
}

// RunSummary is one entry of runs_list.
type RunSummary struct {
	RunID   string  `json:"run_id"`
	Title   string  `json:"title"`
	Status  string  `json:"status"`
	AgentID *string `json:"agent_id"`
}

// RunDetail is runs_get's output; Provenance is TaskProvenance as JSON.
type RunDetail struct {
	RunSummary
	Query      string `json:"query"`
	Provenance any    `json:"provenance"`
}

// RunCommand is runs_send_command's arguments; BudgetUSD is the decimal text given.
type RunCommand struct {
	Command         string
	Message         *string
	MessageID       *string
	ModelInstanceID *string
	BudgetUSD       *string
}

// RunGrant is runs_continue_run's arguments; BudgetUSD is the decimal text given.
type RunGrant struct {
	Iterations, Tokens, ToolCalls int64
	BudgetUSD                     *string
}

// PendingEscalation is one entry of runs_list_pending_escalations.
type PendingEscalation struct {
	EscalationID string         `json:"escalation_id"`
	ToolName     string         `json:"tool_name"`
	ToolCallID   string         `json:"tool_call_id"`
	ToolArgs     map[string]any `json:"tool_args"`
}

// RunEventsPage is runs_get_events' output; each event is an ordered JSON object.
type RunEventsPage struct {
	Total  int64 `json:"total"`
	Events []any `json:"events"`
}

// PlatformRuns is what the platform runs toolset calls (tools/runs_toolset.py).
// Acting on an existing run (cancel through continue_run) needs the run's
// starter or a workspace admin; an escalation's named approvers may decide it.
// Every error's text is what the toolset reports.
type PlatformRuns interface {
	Start(ctx context.Context, c authn.Caller, in RunStart) (RunStarted, error)
	// List is the workspace's runs, newest first; agentID "" for any agent.
	List(ctx context.Context, c authn.Caller, agentID string, limit int) ([]RunSummary, error)
	Get(ctx context.Context, c authn.Caller, runID string) (RunDetail, error)
	Cancel(ctx context.Context, c authn.Caller, runID string) (bool, error)
	Retry(ctx context.Context, c authn.Caller, runID string) error
	Pause(ctx context.Context, c authn.Caller, runID string) (bool, error)
	Resume(ctx context.Context, c authn.Caller, runID string) (bool, error)
	SendInput(ctx context.Context, c authn.Caller, runID, inputRequestID string, answers map[string]any) (bool, error)
	SendCommand(ctx context.Context, c authn.Caller, runID string, cmd RunCommand) (bool, error)
	ResolveEscalation(ctx context.Context, c authn.Caller, runID, escalationID string, approved bool, comment string) (bool, error)
	ListPendingEscalations(ctx context.Context, c authn.Caller, runID string) ([]PendingEscalation, error)
	// ContinueRun answers a grant the run refused as {"accepted": false, "reason": ...}.
	ContinueRun(ctx context.Context, c authn.Caller, runID string, g RunGrant) (ContinueExecutionResult, error)
	Events(ctx context.Context, c authn.Caller, runID string, limit, offset int, eventType *string) (RunEventsPage, error)
}

// InboxItem is one run of inbox_list.
type InboxItem struct {
	ID          string  `json:"id"`
	AgentID     *string `json:"agent_id"`
	Description string  `json:"description"`
	Status      string  `json:"status"`
	CreatedAt   *string `json:"created_at"`
}

// HeldToolCall is one client tool call waiting on a person's approval.
type HeldToolCall struct {
	ID          string  `json:"id"`
	Connector   string  `json:"connector"`
	Tool        string  `json:"tool"`
	RequestedBy string  `json:"requested_by"`
	ClientName  *string `json:"client_name"`
	URL         string  `json:"url"`
	CreatedAt   string  `json:"created_at"`
	ExpiresAt   string  `json:"expires_at"`
}

// InboxPage is inbox_list's output.
type InboxPage struct {
	Items             []InboxItem    `json:"items"`
	Total             int64          `json:"total"`
	Page              int            `json:"page"`
	PageSize          int            `json:"page_size"`
	ToolCallApprovals []HeldToolCall `json:"tool_call_approvals"`
}

// PlatformInbox is what the platform inbox toolset calls (tools/inbox_toolset.py).
type PlatformInbox interface {
	// List is the runs of the inbox statuses (status nil for all of them) and,
	// unless status names another, the pending held tool calls.
	List(ctx context.Context, c authn.Caller, status *string, agentID string, page, pageSize int) (InboxPage, error)
}
