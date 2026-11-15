package api

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// MCPInstanceState is an MCP server instance with what the dashboard and
// the network graph read of it. Verification and LastDispatch are the
// stored objects; JSONSpec the instance's server JSON.
type MCPInstanceState struct {
	ID           string
	WorkspaceID  string
	Name         string
	ServerSpecID string
	NetworkScope string
	ToolCount    int
	JSONSpec     map[string]any
	Verification map[string]any
	LastDispatch map[string]any
	Platform     bool
}

// OpenAPIState is an OpenAPI connection as the network graph shows it.
// BaseURL is nil for a platform-managed connection.
type OpenAPIState struct {
	ID          string
	Name        string
	Description *string
	Status      string
	BaseURL     *string
	ToolCount   int
}

// ConnectionBoard is what the dashboard and the network graph read of connections.
type ConnectionBoard interface {
	// FailingMCPInstances is MCPServerInstanceRepository.list_failing: the
	// workspace's own instances whose verification or last call failed, by name.
	FailingMCPInstances(ctx context.Context, ws scope.Workspace, limit int) ([]MCPInstanceState, error)
	// MCPInstances is every instance the workspace sees: its own and the platform's.
	MCPInstances(ctx context.Context, ws scope.Workspace) ([]MCPInstanceState, error)
	// OpenAPIConnections is the workspace's own OpenAPI connections.
	OpenAPIConnections(ctx context.Context, ws scope.Workspace) ([]OpenAPIState, error)
}
