package transport

import (
	"context"
	"errors"
)

// ErrMCPEventsNotBuilt is the error every mcp_events poll returns until the
// transport exists: MCP Events polls go through the mcp-manager gateway, so the
// instance's credentials stay there (ADR-0040 Plan, phase 5).
var ErrMCPEventsNotBuilt = errors.New("the mcp_events poll transport is not built yet; use the webhook mode of this source")

// MCPEventsTransport stands in for the MCP Events poll (events/poll through the
// gateway).
type MCPEventsTransport struct{}

// Fetch fails: nothing polls MCP Events yet.
func (MCPEventsTransport) Fetch(context.Context, Fetch) (Result, error) {
	return Result{}, ErrMCPEventsNotBuilt
}
