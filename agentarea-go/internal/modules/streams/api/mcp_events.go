package api

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// Error codes of the MCP Events extension (SEP-3415).
const (
	EventsInvalidParams     = -32602
	EventsNotFound          = -32023
	EventsForbidden         = -32024
	EventsResourceExhausted = -32025
	EventsUnsupported       = -32026
	EventsCallbackError     = -32027
)

// EventsError is a JSON-RPC error of the events extension, by its code.
type EventsError struct {
	Code    int
	Message string
	Data    map[string]any
}

func (e *EventsError) Error() string { return e.Message }

// EventsScope is the workspaces one MCP mount serves its caller (mcp_events.EventsScope).
type EventsScope interface {
	Workspaces(ctx context.Context) ([]authn.Caller, error)
	// Enter is the caller in the workspace an event name holds, by slug or id; an *EventsError
	// when the mount does not reach it.
	Enter(ctx context.Context, workspace string) (authn.Caller, error)
}

// MCPEvents serves the platform's streams as an MCP Events server: events/list, events/poll,
// events/subscribe and events/unsubscribe.
type MCPEvents interface {
	// Serve answers method; an *EventsError is the JSON-RPC error to answer with.
	Serve(ctx context.Context, scope EventsScope, method string, params json.RawMessage) (any, error)
}

// EventsMethods are the methods MCPEvents serves.
func EventsMethods() []string {
	return []string{"events/list", "events/poll", "events/subscribe", "events/unsubscribe"}
}
