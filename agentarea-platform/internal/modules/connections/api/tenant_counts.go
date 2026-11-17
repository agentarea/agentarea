package api

import "context"

// Connectors is a count of connectors from one catalog source with one auth type.
type Connectors struct {
	// Source is the MCP instance's server spec id or the OpenAPI connection's registry item id;
	// "" is none.
	Source string
	// AuthType is the auth config's type, "none" without one.
	AuthType string
	Count    int
}

// TenantCounts are connections' counts over every tenant workspace.
type TenantCounts struct {
	MCP, OpenAPI  int
	MCPBySpec     []Connectors
	OpenAPIByItem []Connectors
	// MCPByVerification are MCP instances by verification status, "unknown" without one.
	MCPByVerification map[string]int
}

// TenantCounter is analytics/pulse_repository.py's connectors (by_kind, by_catalog, by_auth_type, by_verification_status).
type TenantCounter interface {
	TenantCounts(ctx context.Context) (TenantCounts, error)
}
