package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// OpenAPICall is a run's call of one operation of an OpenAPI connection.
type OpenAPICall struct {
	// UserID is who the run acts for; the connection's secrets are read as them.
	UserID string
	// AgentID is the run's agent; the call goes through only when it may use the connection.
	AgentID      string
	ConnectionID string
	// Operation is the operation's name in the spec (its operationId), or the
	// tool name it is served under.
	Operation  string
	Args       map[string]any
	ToolCallID string
	Paid       PaidCall
}

// OpenAPIResult is what the call answered (OpenAPITool.execute).
type OpenAPIResult struct {
	Success bool
	// Result is the answer's text, capped at 64 KB; Error the failure's.
	Result string
	Error  string
	// StatusCode is 0 when no response came back.
	StatusCode int
	// Body is the decoded JSON answer, untruncated, for the meter.
	Body any
	// ToolName is the operation's tool name (_slugify_name).
	ToolName string
	Payments []Payment
}

// OpenAPITools runs OpenAPI connection operations for runs. A successful
// call is stamped as the connection's last dispatch.
type OpenAPITools interface {
	CallOpenAPI(ctx context.Context, ws scope.Workspace, call OpenAPICall) OpenAPIResult
}
