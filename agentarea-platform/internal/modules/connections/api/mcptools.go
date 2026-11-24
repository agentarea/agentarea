package api

import "context"

// MCPCall is one tools/call a run makes on an MCP server instance.
type MCPCall struct {
	WorkspaceID string
	UserID      string
	AgentID     string
	TaskID      string
	ToolCallID  string
	// InstanceID is the instance the binding names; a bundle routes to its member.
	InstanceID string
	// Tool is the server's own tool name (not the model-facing one).
	Tool string
	Args map[string]any
	// TaskMetadata is the run's metadata: its end_user_id and app_metadata
	// reach a server that takes caller context.
	TaskMetadata map[string]any
	Progress     func(progress float64, total *float64, message string)
	// Paid keys the payments of a 402 the agent's wallet answers; an empty
	// CallRef leaves a 402 unpaid.
	Paid PaidCall
}

// MCPImage is an image a tool returned, as raw bytes.
type MCPImage struct {
	MimeType string
	Data     []byte
}

// MCPResult is the call's outcome; a failed call is Success false, not an error.
type MCPResult struct {
	Success          bool
	Result           string
	Error            string
	ToolName         string
	ServerInstanceID string
	// Meta is the result's _meta (a cost the server reports).
	Meta                     map[string]any
	StructuredContent        any
	StructuredContentDropped bool
	Images                   []MCPImage
	Payments                 []Payment
}

// MCPTools runs tool calls on MCP server instances (execute_tool). The
// instance's endpoint, credentials and context signing are resolved per call.
type MCPTools interface {
	Call(ctx context.Context, call MCPCall) (MCPResult, error)
}
