package transport

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/event-service/internal/mcpevents"
)

const (
	// mcpMaxEvents caps one events/poll; hasMore drains the rest at once.
	mcpMaxEvents = 100
	// mcpMaxDrains bounds the polls one Fetch runs while the server has more.
	mcpMaxDrains = 20
	// mcpMinNextPoll is the floor on the wait a server asks for.
	mcpMinNextPoll = time.Second
)

// MCPEventsPoller is the events/poll half of the MCP Events client.
type MCPEventsPoller interface {
	Poll(ctx context.Context, instanceID string, req mcpevents.PollRequest) (mcpevents.PollResult, error)
}

// MCPEventsTransport polls an MCP server's events/poll through the mcp-manager
// gateway. The source's config names the event and its arguments; the cursor
// is the server's opaque one, "" before the first poll, which starts from now.
type MCPEventsTransport struct {
	poller MCPEventsPoller
}

// NewMCPEventsTransport builds the transport over an MCP Events client.
func NewMCPEventsTransport(poller MCPEventsPoller) *MCPEventsTransport {
	return &MCPEventsTransport{poller: poller}
}

// MCPEventsConfig is what an mcp_events source names.
type MCPEventsConfig struct {
	Event     string
	Arguments map[string]any
}

// ReadMCPEventsConfig reads the event and its arguments (a JSON object) from a
// source's config.
func ReadMCPEventsConfig(config map[string]any) (MCPEventsConfig, error) {
	event, _ := config["event"].(string)
	if event == "" {
		return MCPEventsConfig{}, errors.New("the source names no event")
	}
	arguments := map[string]any{}
	if raw, _ := config["arguments"].(string); raw != "" {
		if err := json.Unmarshal([]byte(raw), &arguments); err != nil || arguments == nil {
			return MCPEventsConfig{}, fmt.Errorf("the source's arguments are not a JSON object")
		}
	}
	return MCPEventsConfig{Event: event, Arguments: arguments}, nil
}

// Fetch polls until the server has nothing more, oldest event first.
func (t *MCPEventsTransport) Fetch(ctx context.Context, f Fetch) (Result, error) {
	if f.MCPInstanceID == "" {
		return Result{}, errors.New("the source names no MCP server of its workspace")
	}
	cfg, err := ReadMCPEventsConfig(f.Values.Config)
	if err != nil {
		return Result{}, err
	}
	var cursor *string
	if f.Values.Cursor != "" {
		stored := f.Values.Cursor
		cursor = &stored
	}
	var result Result
	for range mcpMaxDrains {
		answer, err := t.poller.Poll(ctx, f.MCPInstanceID, mcpevents.PollRequest{
			Name: cfg.Event, Arguments: cfg.Arguments, Cursor: cursor, MaxEvents: mcpMaxEvents,
		})
		if err != nil {
			return Result{}, err
		}
		if answer.Truncated && cursor != nil {
			result.Gap = "the MCP server skipped events after the stored cursor (truncated)"
		}
		for _, event := range answer.Events {
			result.Items = append(result.Items, event)
		}
		if answer.Cursor != nil {
			result.Cursor = *answer.Cursor
			cursor = answer.Cursor
		}
		result.Next = 0
		if answer.NextPollMs > 0 {
			result.Next = max(time.Duration(answer.NextPollMs)*time.Millisecond, mcpMinNextPoll)
		}
		if !answer.HasMore || answer.Cursor == nil {
			return result, nil
		}
	}
	return result, nil
}
