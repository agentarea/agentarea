package api

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// ClientSummary is clients_toolset._summary.
type ClientSummary struct {
	ID             string
	Name           string
	Kind           string
	MCPEndpointURL string
}

// Clients is what the platform MCP clients toolset (tools/clients_toolset.py)
// calls. Each method checks the relation @requires names on the client, as
// the REST routes do; a refusal of the input is an error whose text is what
// the toolset reports.
type Clients interface {
	// List is every client the caller may read (readable_resource_ids).
	List(ctx context.Context, c authn.Caller, limit, offset int) ([]ClientSummary, error)
	// Get is the ClientResponse document; ErrNotFound for an unknown client.
	Get(ctx context.Context, c authn.Caller, clientID string) (json.RawMessage, error)
	// Create takes a ClientCreate document.
	Create(ctx context.Context, c authn.Caller, clientCreate json.RawMessage) (ClientSummary, error)
	// Update takes a ClientUpdate document (the keys the tool was given).
	Update(ctx context.Context, c authn.Caller, clientID string, clientUpdate json.RawMessage) (ClientSummary, error)
	// Delete reports whether a client was deleted; agents running on it refuse it.
	Delete(ctx context.Context, c authn.Caller, clientID string) (bool, error)
	AddSkill(ctx context.Context, c authn.Caller, clientID, skillID string) error
	RemoveSkill(ctx context.Context, c authn.Caller, clientID, skillID string) error
	// AddMCPInstance attaches an instance or replaces how it is served; nil allowed serves all its tools.
	AddMCPInstance(ctx context.Context, c authn.Caller, clientID, instanceID string, namespacePrefix *string, allowedTools []string) error
	RemoveMCPInstance(ctx context.Context, c authn.Caller, clientID, instanceID string) error
	AddOpenAPIConnection(ctx context.Context, c authn.Caller, clientID, connectionID string, namespacePrefix *string, allowedTools []string) error
	RemoveOpenAPIConnection(ctx context.Context, c authn.Caller, clientID, connectionID string) error
	// AddPlatformToolset attaches a toolset by name or namespace and returns its namespace.
	AddPlatformToolset(ctx context.Context, c authn.Caller, clientID, toolset string, disabledMethods []string) (string, error)
	RemovePlatformToolset(ctx context.Context, c authn.Caller, clientID, toolset string) error
}
