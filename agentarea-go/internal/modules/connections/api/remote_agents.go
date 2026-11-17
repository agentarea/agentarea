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
	Paid           PaidCall
}

// RemoteAgentResult is what the delegate answered (A2AAgentTool.execute). Raised marks a
// failure the tool raised (ToolExecutionError) rather than answered; Error is its message.
type RemoteAgentResult struct {
	Success  bool
	Result   string
	Error    string
	Raised   bool
	Payments []Payment
}

// RemoteAgents calls runs' remote A2A delegates; an error is the call cancelled.
type RemoteAgents interface {
	CallRemoteAgent(ctx context.Context, call RemoteAgentCall) (RemoteAgentResult, error)
}
