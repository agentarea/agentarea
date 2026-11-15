package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// ErrConnectionGone: no MCP instance or OpenAPI connection has the id.
var ErrConnectionGone = errors.New("the connection no longer exists")

// SettledCosts reads what a settled call cost from its vendor
// (vendor_settlement.py): the connection's catalog cost declaration for a
// tool, and one GET with the connection's own credential.
type SettledCosts interface {
	// SettledDeclaration is the cost declaration the connection's catalog
	// entry makes for tool (mcp_tool_connection, openapi_tool_connection);
	// nil when it declares none. ErrConnectionGone when the id names nothing.
	SettledDeclaration(ctx context.Context, ws scope.Workspace, userID, connectionID, tool string) (map[string]any, error)
	// FetchSettlement GETs url with the connection's credential headers
	// through netguard (a member destination), bounded by 20 seconds.
	FetchSettlement(ctx context.Context, ws scope.Workspace, userID, connectionID, url string) (status int, body []byte, err error)
}
