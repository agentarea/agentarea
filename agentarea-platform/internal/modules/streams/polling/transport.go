package polling

import (
	"context"
	"fmt"
	"time"
)

// Fetch is one poll of one source.
type Fetch struct {
	SourceID string
	Poll     Poll
	// Values fill the poll block's templates; Values.Cursor is the stored position.
	Values Values
	// MCPInstanceID is the MCP server an mcp_events source names, when it is one of the
	// source's own workspace.
	MCPInstanceID string
}

// Result is what one poll found, oldest item first.
type Result struct {
	Items []any
	// Cursor is the position after the last item; "" keeps the stored one.
	Cursor string
	// Gap, when set, says why items between the last poll and this one may be missing.
	Gap string
	// Next is the wait the source asks for before the next poll; 0 keeps the entry's interval.
	Next time.Duration
}

// Transport fetches what a source has new since its cursor. A transport is a protocol,
// never a provider: what to call comes from the entry's poll block.
type Transport interface {
	Fetch(ctx context.Context, f Fetch) (Result, error)
}

// Transports is every transport the pollers run, by name.
type Transports map[string]Transport

// NewTransports builds the four transports.
func NewTransports(caller *Caller, dial DialFunc, mcp MCPEventsPoller) Transports {
	return Transports{
		HTTPJSON:  &HTTPJSONTransport{caller: caller},
		Feed:      &FeedTransport{caller: caller},
		IMAP:      &IMAPTransport{dial: dial},
		MCPEvents: &MCPEventsTransport{poller: mcp},
	}
}

// Get returns the transport a poll block names.
func (s Transports) Get(name string) (Transport, error) {
	t, ok := s[name]
	if !ok {
		return nil, fmt.Errorf("poll transport %q is not one of http_json, feed, imap, mcp_events", name)
	}
	return t, nil
}
