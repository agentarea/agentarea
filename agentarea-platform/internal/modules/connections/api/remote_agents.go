package api

import "context"

// RemoteAgentCall is a run's call of a remote delegate: its message sent to the A2A agent at
// A2AURL, with the workspace secret AuthSecretName as the bearer when one is bound.
type RemoteAgentCall struct {
	WorkspaceID string
	// UserID is who the run acts for; the secret is read as them.
	UserID string
	// AgentID is the run's agent; its wallet pays a 402.
	AgentID        string
	AgentName      string
	ToolName       string
	ToolCallID     string
	A2AURL         string
	AuthSecretName string
	Message        string
	// MessageID is the A2A messageId, the same on every attempt of one call so a retried
	// send never starts a second remote task.
	MessageID string
	Paid      PaidCall
}

// RemoteAgentResult is what the delegate answered (A2AAgentTool.execute). Raised marks a
// failure the tool raised (ToolExecutionError) rather than answered; Error is its message.
// Pending is the task the delegate is still working on; the result is then not known yet.
type RemoteAgentResult struct {
	Success  bool
	Result   string
	Error    string
	Raised   bool
	Pending  *RemoteTask
	Payments []Payment
}

// RemoteTask is a task a remote delegate runs: its id and the JSON-RPC endpoint it lives on.
type RemoteTask struct {
	ID       string
	Endpoint string
	// Legacy is an A2A 0.3 endpoint.
	Legacy bool
}

// RemoteTaskCall asks a remote delegate about one of its tasks, as the run's user.
type RemoteTaskCall struct {
	WorkspaceID    string
	UserID         string
	AgentName      string
	A2AURL         string
	AuthSecretName string
	Task           RemoteTask
}

// RemoteAgents calls runs' remote A2A delegates; an error is the call cancelled.
type RemoteAgents interface {
	// SendRemoteAgent sends the message without waiting for the task it starts.
	SendRemoteAgent(ctx context.Context, call RemoteAgentCall) (RemoteAgentResult, error)
	// GetRemoteAgentTask reads the task once; Pending while it still runs.
	GetRemoteAgentTask(ctx context.Context, call RemoteTaskCall) (RemoteAgentResult, error)
	// CancelRemoteAgentTask asks the delegate to stop the task.
	CancelRemoteAgentTask(ctx context.Context, call RemoteTaskCall) error
}
