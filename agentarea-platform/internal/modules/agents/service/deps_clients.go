package service

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// ClientMCPNames names the MCP server instances a workspace sees: its own and
// the platform's (connections api.Lookup).
type ClientMCPNames interface {
	MCPInstanceNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
}

// ClientConnections is what attaching connections to a client reads (connections module).
type ClientConnections interface {
	// MCPInstance: found when ws sees the instance (its own or the platform's);
	// platform when the platform manages it (managed_by).
	MCPInstance(ctx context.Context, ws scope.Workspace, id string) (found, platform bool, err error)
	// OpenAPIConnection is MCPInstance for an OpenAPI connection.
	OpenAPIConnection(ctx context.Context, ws scope.Workspace, id string) (found, platform bool, err error)
	// OpenAPIConnectionNames maps each id of ids ws sees to its name.
	OpenAPIConnectionNames(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error)
}

// ClientRunnerKey is an API key of a client's runner (api_keys row).
type ClientRunnerKey struct {
	ID         string
	Name       string
	Prefix     string
	CreatedBy  string
	CreatedAt  time.Time
	LastUsedAt *time.Time
	ClientID   *string
	Active     bool
}

// ClientRunnerKeys issues and revokes runner keys (identity module, APIKeyService).
type ClientRunnerKeys interface {
	// Issue creates a key named name bound to clientID; key is the secret, shown once.
	Issue(ctx context.Context, c authn.Caller, clientID, name string) (ClientRunnerKey, string, error)
	// List is every key bound to clientID, revoked ones included.
	List(ctx context.Context, c authn.Caller, clientID string) ([]ClientRunnerKey, error)
	// Get is the workspace's key, false when it has none.
	Get(ctx context.Context, c authn.Caller, keyID string) (ClientRunnerKey, bool, error)
	Revoke(ctx context.Context, c authn.Caller, keyID string) error
}

// ClientPorts are the client routes' own ports; a nil port answers 501 where it is needed.
type ClientPorts struct {
	// APIURL is AppSettings.API_URL, the base of each client's mcp_endpoint_url.
	APIURL      string
	MCPNames    ClientMCPNames
	Connections ClientConnections
	RunnerKeys  ClientRunnerKeys
}
