package channels

import (
	"context"

	"github.com/agentarea/event-service/internal/submit"
)

// PolledEvent is one event with the routing metadata of the chat it came from.
// A batch can span chats, so each event carries its own origin.
type PolledEvent struct {
	Event         submit.Event
	ChannelOrigin map[string]any
}

// PollResult holds the output of a single poll cycle.
type PollResult struct {
	Events    []PolledEvent
	NewOffset int64 // 0 means "don't advance"
}

// ChannelPoller abstracts polling for a specific channel type (Telegram, WhatsApp, etc.).
type ChannelPoller interface {
	// Poll fetches new events since the given offset.
	// Returns events, each with its channel routing metadata.
	// A zero-length Events slice means no new data.
	Poll(ctx context.Context, offset int64) (*PollResult, error)
}

// Factory creates a ChannelPoller from trigger config.
// Returns nil if the extractor type is not supported.
type Factory func(config map[string]any) ChannelPoller
