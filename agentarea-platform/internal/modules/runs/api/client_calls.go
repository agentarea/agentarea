package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// CostDeclarationError: the connector's cost declaration for the tool is malformed or names a
// payer it does not allow (ToolCostError); the call cannot be priced, so it does not run.
type CostDeclarationError struct{ Msg string }

func (e *CostDeclarationError) Error() string { return e.Msg }

// ToolCosts is mcp_tool_connection and openapi_tool_connection: what the connection a binding
// runs on declares the tool costs, and who pays, read when the call is made. Nil for a binding
// on no connection or one that no longer exists.
type ToolCosts interface {
	ToolCost(ctx context.Context, ws scope.Workspace, b ToolBinding) (*ToolCost, error)
}

// ClientToolCall is one call a person or a registered client makes outside any run. Binding
// names the connection it runs on (Source mcp or openapi); a platform tool has none.
type ClientToolCall struct {
	UserID, ClientID string
	ToolName         string
	Args             map[string]any
	Binding          ToolBinding
}

// ClientToolAnswer is what the call answered, as metering reads it.
type ClientToolAnswer struct {
	Success    bool
	Body       any
	Meta       map[string]any
	VendorCost *money.Decimal
}

// ClientCallHooks are the caller's halves of the layer: Audit files the verdict ("" allows) before
// anything runs; Invoke runs the call.
type ClientCallHooks struct {
	Audit  func(ctx context.Context, refusal string) error
	Invoke func(ctx context.Context) (ClientToolAnswer, error)
}

// ClientToolCalls is run_tool_call for a call outside a run, after the policy allowed it: the
// cost known before it, a hold on the platform's key, the spend caps (the client's included),
// the call, and its cost lines with the client and no task. A refusal is returned, not raised.
type ClientToolCalls interface {
	RunClientCall(ctx context.Context, ws scope.Workspace, call ClientToolCall, h ClientCallHooks) (refusal string, err error)
}
