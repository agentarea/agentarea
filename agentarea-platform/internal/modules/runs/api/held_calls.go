package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// HeldCall is one call outside a run the policy holds for approval, as the client made it
// (ToolCallRequest). MCPInstanceID is empty for a platform tool or an OpenAPI operation.
type HeldCall struct {
	UserID                      string
	MCPInstanceID               string
	Connector, Tool, PolicyName string
	Arguments                   map[string]any
	Reason                      string
	Approvers                   []string
	ClientID, ClientName        *string
}

// What a held call's approval says.
const (
	HeldRun      = "run"
	HeldPending  = "pending"
	HeldRejected = "rejected"
)

// HeldOutcome is the gate's verdict and the approval it read: the one consumed, the rejection,
// or the open request with its page.
type HeldOutcome struct {
	Verdict, ApprovalID string
	DecidedBy           string
	Comment             *string
	Connector, Tool     string
	URL                 string
}

// HeldCalls is ToolCallApprovalService.gate: run with a live approval of this exact call, else
// answer with its approval. A rejected call is answered with the rejection until its deadline;
// an open request is reused; otherwise one is recorded. It writes in tx, which the caller
// commits with the verdict's audit row.
type HeldCalls interface {
	Gate(ctx context.Context, tx db.Session, ws scope.Workspace, call HeldCall) (HeldOutcome, error)
}
