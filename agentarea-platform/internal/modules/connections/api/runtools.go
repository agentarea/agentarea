package api

import (
	"context"
	"errors"

	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

// RunToolsRequest asks for the tools an agent's run may use: the agent's
// saved tools plus the MCP instances its starter selected for the run.
type RunToolsRequest struct {
	WorkspaceID string
	// UserID started the run; a selected connection must be one they may use.
	UserID         string
	AgentID        string
	TaskID         string
	Agent          runsapi.AgentSpec
	MCPInstanceIDs []string
}

// RunToolSet is every tool a run may call (discover_available_tools_split,
// discover_tool_providers and openapi_operation_tools in one read). Its
// fields match runs' service.ToolSet, so the app converts it as is.
type RunToolSet struct {
	Tools                 []runsapi.ToolDefinition
	SearchableTools       []runsapi.SearchableTool
	ToolProviders         []runsapi.ToolProvider
	Bindings              map[string]runsapi.ToolBinding
	OpenAPIOperationTools map[string][]string
}

// ErrToolsNotFound: a connection the run selected does not exist or is not
// visible. ErrToolsRefused: a connection exists but this run may not call
// through it. Both are final; any other error may be retried.
var (
	ErrToolsNotFound = errors.New("not found")
	ErrToolsRefused  = errors.New("refused")
)

// RunTools resolves a run's tools once, at its start.
type RunTools interface {
	RunTools(ctx context.Context, req RunToolsRequest) (RunToolSet, error)
}
