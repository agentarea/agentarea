package api

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// ErrNotFound: the workspace has no such connection, instance or spec.
var ErrNotFound = errors.New("not found")

// CatalogConnection is one of the caller's connections made from a catalog item.
type CatalogConnection struct {
	ID, Kind, Name string
}

// CatalogConnections lists the caller's connections made from catalog items.
type CatalogConnections interface {
	// CatalogConnections is readable_catalog_connections: per item id, the
	// connections the graph lets the caller read, oldest first.
	CatalogConnections(ctx context.Context, c authn.Caller, itemIDs []string) (map[string][]CatalogConnection, error)
}

// ConnectAction is a link a person must open before the connection can be used.
type ConnectAction struct {
	URL, Message string
	// ExistingConnections are the caller's other connections from the same
	// catalog item; nil when there are none.
	ExistingConnections []CatalogConnection
}

// MCPSpec is an MCP server spec as mcp_servers_get_spec returns it.
type MCPSpec struct {
	ID, Name, Description, Version string
	Tags                           []any
	IsPublic                       bool
	RemoteURL, DockerImageURL      *string
	Status                         string
	EnvSchema                      []any
	RegistryURL                    *string
}

// SpecListing is list_specs' filters; nil is no filter.
type SpecListing struct {
	IsPublic      *bool
	Tag, Search   *string
	Limit, Offset int
}

// MCPInstance is an MCP server instance as the mcp_servers toolset returns it.
type MCPInstance struct {
	ID, Name     string
	Description  *string
	Verification any
	ServerSpecID string
	LastDispatch map[string]any
	Tools        []any
	// ActionRequired is set while the instance waits on a sign-in or key.
	ActionRequired *ConnectAction
}

// PlatformMCPServers is what the platform mcp_servers toolset calls
// (tools/mcp_servers_toolset.py). Each method checks
// what the tool's authorization marker demands (the REST route's relation);
// documents are checked with the REST bodies' rules. A refusal is an error
// whose text the toolset reports.
type PlatformMCPServers interface {
	// GetSpec returns ErrNotFound for an unknown spec; a tenant spec needs
	// read on it, catalog data does not.
	GetSpec(ctx context.Context, c authn.Caller, specID string) (MCPSpec, error)
	// CreateSpec takes an MCPServerCreate document; the caller owns the spec.
	CreateSpec(ctx context.Context, c authn.Caller, doc json.RawMessage) (MCPSpec, error)
	// UpdateSpec takes an MCPServerUpdate document; ErrNotFound for a spec
	// the workspace does not have.
	UpdateSpec(ctx context.Context, c authn.Caller, specID string, doc json.RawMessage) (MCPSpec, error)
	// DeleteSpec is false when there was no such spec.
	DeleteSpec(ctx context.Context, c authn.Caller, specID string) (bool, error)
	// ListSpecs is a page of the readable workspace specs then the catalog, and the total.
	ListSpecs(ctx context.Context, c authn.Caller, q SpecListing) ([]MCPSpec, int, error)
	// Create takes an MCPServerInstanceCreate document; the connect action is probed.
	Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (MCPInstance, error)
	// Update takes an MCPServerInstanceUpdate document; ErrNotFound for an
	// unknown instance; the connect action is probed.
	Update(ctx context.Context, c authn.Caller, instanceID string, doc json.RawMessage) (MCPInstance, error)
	List(ctx context.Context, c authn.Caller) ([]MCPInstance, error)
	// Get returns ErrNotFound for an unknown instance; the connect action is
	// read from what is recorded, never probed.
	Get(ctx context.Context, c authn.Caller, instanceID string) (MCPInstance, error)
	// Delete is false when there was no such instance.
	Delete(ctx context.Context, c authn.Caller, instanceID string) (bool, error)
	// Verify runs verification and returns the stored payload, and the
	// probed connect action when the instance waits on a credential.
	Verify(ctx context.Context, c authn.Caller, instanceID string) (verification any, action *ConnectAction, err error)
}

// NamedField is a configured header or query parameter: its name, never its value.
type NamedField struct {
	Name   string
	Secret bool
}

// OpenAPITool is a tool discovered from a connection's spec.
type OpenAPITool struct {
	Name, Description string
}

// OpenAPIConnection is an OpenAPI connection as the toolset returns it.
type OpenAPIConnection struct {
	ID, Name    string
	Description *string
	// BaseURL is nil for a connection the platform provides.
	BaseURL, SpecURL, AuthConfigID *string
	CustomHeaders                  []NamedField
	CustomQueryParams              []NamedField
	URLVariables                   []string
	Tools                          []OpenAPITool
	Status                         string
	LastDispatch                   map[string]any
}

// OpenAPIDiscovery is what a discovery stored.
type OpenAPIDiscovery struct {
	ConnectionID string
	Tools        []OpenAPITool
}

// PlatformOpenAPI is what the platform openapi_connections toolset calls
// (tools/openapi_connections_toolset.py); authorization and refusals as
// PlatformMCPServers'.
type PlatformOpenAPI interface {
	// Create takes an OpenAPIConnectionCreate document.
	Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (OpenAPIConnection, error)
	// List is a page of the connections matching search, and the total.
	List(ctx context.Context, c authn.Caller, search string, limit, offset int) ([]OpenAPIConnection, int, error)
	// Get returns ErrNotFound for an unknown connection.
	Get(ctx context.Context, c authn.Caller, connectionID string) (OpenAPIConnection, error)
	// Update takes an OpenAPIConnectionUpdate document; ErrNotFound for an unknown connection.
	Update(ctx context.Context, c authn.Caller, connectionID string, doc json.RawMessage) (OpenAPIConnection, error)
	DiscoverTools(ctx context.Context, c authn.Caller, connectionID string) (OpenAPIDiscovery, error)
	// Delete is false when there was no such connection.
	Delete(ctx context.Context, c authn.Caller, connectionID string) (bool, error)
}

// ConnectorTool is one tool of a connector; Hint is "destructive",
// "read-only" or empty.
type ConnectorTool struct {
	Name, Description, Title, Hint string
	InputSchema                    any
}

// Connector is an MCP server instance or an OpenAPI connection with its tools.
type Connector struct {
	ID, Name string
	Tools    []ConnectorTool
}

// ConnectorCall is what a connector's tool answered, or why it did not run:
// exactly one of Content (with IsError and StructuredContent),
// ConfirmationRequired and ActionRequired is set.
type ConnectorCall struct {
	ConnectorID, Connector, Tool string
	Content                      []map[string]any
	StructuredContent            any
	IsError                      bool
	ConfirmationRequired         bool
	ActionRequired               *ConnectAction
}

// ErrNoConnector: no connector has the id or name.
var ErrNoConnector = errors.New("no connector")

// AmbiguousConnectorError: more than one connector has the name.
type AmbiguousConnectorError struct{ IDs []string }

func (e *AmbiguousConnectorError) Error() string { return "ambiguous connector name" }

// UnknownToolError: the connector has no tool by that name; Names are its tools.
type UnknownToolError struct {
	Connector string
	Names     []string
}

func (e *UnknownToolError) Error() string { return e.Connector + " has no such tool" }

// ToolCallFailedError: the call did not reach an answer.
type ToolCallFailedError struct {
	Connector string
	Err       error
}

func (e *ToolCallFailedError) Error() string { return e.Err.Error() }
func (e *ToolCallFailedError) Unwrap() error { return e.Err }

// PlatformConnectorTools is what the platform tools toolset calls
// (tools/connector_tools_toolset.py).
type PlatformConnectorTools interface {
	// Searchable is the connectors a search covers: the readable (or
	// platform-managed) verified MCP instances and active OpenAPI
	// connections, only the one named by connector when it is set.
	Searchable(ctx context.Context, c authn.Caller, connector *string) ([]Connector, error)
	// Call runs tool on the connector named by id or name after use_connection
	// on it; the workspace policy judges the call. A destructive tool runs
	// only with confirm. ErrNoConnector, *AmbiguousConnectorError,
	// *UnknownToolError and *ToolCallFailedError are the refusals.
	Call(ctx context.Context, c authn.Caller, connector, tool string, args json.RawMessage, confirm bool) (ConnectorCall, error)
}

// PlatformCall is one call of a platform toolset method from a run: it acts
// as the run's agent in its workspace, attributed to the run's user.
type PlatformCall struct {
	WorkspaceID string
	UserID      string
	AgentID     string
	// Namespace is agentarea/<toolset>; Method the toolset's method.
	Namespace string
	Method    string
	Args      json.RawMessage
}

// PlatformResult is the call's tool result: its text, and whether it failed.
type PlatformResult struct {
	Text              string
	IsError           bool
	StructuredContent any
}

// PlatformTools runs platform toolset methods for runs, the same tools
// /mcp/w/{workspace} serves.
type PlatformTools interface {
	// Call answers ErrUnknownPlatformTool for a namespace or method no
	// served toolset has.
	Call(ctx context.Context, call PlatformCall) (PlatformResult, error)
}

// ErrUnknownPlatformTool: no served platform toolset has the method.
var ErrUnknownPlatformTool = errors.New("unknown platform tool")
