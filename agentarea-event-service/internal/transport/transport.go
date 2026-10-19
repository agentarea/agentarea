// Package transport fetches the raw items of a poll source. A transport is a
// protocol (http_json, feed, imap, mcp_events), never a provider: what to
// call and where the items are comes from the catalog entry's poll block.
// Nothing here parses an item for meaning or builds an event key.
package transport

import (
	"context"
	"fmt"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/egress"
	"github.com/agentarea/event-service/internal/template"
)

// Transport names in a catalog entry's poll block.
const (
	HTTPJSON  = "http_json"
	Feed      = "feed"
	IMAP      = "imap"
	MCPEvents = "mcp_events"
)

// Fetch is one poll of one source.
type Fetch struct {
	SourceID string
	Poll     catalog.Poll
	// Values fill the poll block's templates; Values.Cursor is the stored
	// position, "" before the first poll.
	Values template.Values
}

// Result is what one poll found, oldest item first.
type Result struct {
	Items []any
	// Cursor is the position after the last item; "" keeps the stored one.
	Cursor string
	// Gap, when set, says why items between the last poll and this one may be
	// missing (a truncated result, a cursor the source no longer knows).
	Gap string
}

// Transport fetches what a source has new since its cursor.
type Transport interface {
	Fetch(ctx context.Context, f Fetch) (Result, error)
}

// Set is every transport the service runs, by name.
type Set map[string]Transport

// NewSet builds the transports over one outbound policy.
func NewSet(policy egress.Policy) Set {
	caller := NewCaller(policy)
	return Set{
		HTTPJSON:  &HTTPJSONTransport{caller: caller},
		Feed:      &FeedTransport{caller: caller},
		IMAP:      &IMAPTransport{policy: policy},
		MCPEvents: MCPEventsTransport{},
	}
}

// Get returns the transport a poll block names.
func (s Set) Get(name string) (Transport, error) {
	t, ok := s[name]
	if !ok {
		return nil, fmt.Errorf("poll transport %q is not one of http_json, feed, imap, mcp_events", name)
	}
	return t, nil
}
