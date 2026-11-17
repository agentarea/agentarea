package api

import (
	"context"

	"github.com/google/uuid"
)

// DeclaredMCP is a platform-declared remote MCP instance of the platform server ServerID; Token
// is sent as its bearer Authorization. EndpointChanged resets its verification and tool snapshot.
type DeclaredMCP struct {
	InstanceID, ServerID uuid.UUID
	Name, Description    string
	EndpointChanged      bool
	Token                string
}

// DeclaredOpenAPI is a platform-declared OpenAPI connection of a catalog item; its spec is fetched
// from SpecURL on every declaration.
type DeclaredOpenAPI struct {
	ID, RegistryItemID uuid.UUID
	Name, Description  string
	SpecURL, BaseURL   string
	Token              string
}

// PlatformConnections is what the operator writes of connections' tables. Every write is idempotent.
type PlatformConnections interface {
	DeclareMCP(ctx context.Context, d DeclaredMCP) error
	DeclareOpenAPI(ctx context.Context, d DeclaredOpenAPI) error
}
