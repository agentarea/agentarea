package mcpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	streamsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
)

// maxOffset is MAX_OFFSET: the highest offset a paged list takes.
const maxOffset = 1_000_000_000

// checkRange is _check_range: the REST routes' Query bounds; hi < lo means no upper bound.
func checkRange(name string, value, lo, hi int64) error {
	if value >= lo && (hi < lo || value <= hi) {
		return nil
	}
	if hi < lo {
		return &toolError{fmt.Sprintf("%s must be at least %d, got %d", name, lo, value)}
	}
	return &toolError{fmt.Sprintf("%s must be between %d and %d, got %d", name, lo, hi, value)}
}

type streamIDArgs struct {
	StreamID string `json:"stream_id"`
}

type streamSubArgs struct {
	StreamID       string `json:"stream_id"`
	SubscriptionID string `json:"subscription_id"`
}

func deleted() map[string]any { return map[string]any{"deleted": true} }

// streamCall decodes the stream id and hands it to f.
func streamCall(f func(ctx context.Context, c authn.Caller, streamID string) (any, error)) func(context.Context, authn.Caller, json.RawMessage) (any, error) {
	return func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
		in, err := decodeArgs[streamIDArgs](args)
		if err != nil {
			return nil, err
		}
		return f(ctx, c, in.StreamID)
	}
}

// subscriptionDelete decodes the stream and subscription ids and answers {"deleted": true}.
func subscriptionDelete(f func(ctx context.Context, c authn.Caller, streamID, subID string) error) func(context.Context, authn.Caller, json.RawMessage) (any, error) {
	return func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
		in, err := decodeArgs[streamSubArgs](args)
		if err != nil {
			return nil, err
		}
		if err := f(ctx, c, in.StreamID, in.SubscriptionID); err != nil {
			return nil, err
		}
		return deleted(), nil
	}
}

// parseMoment is a datetime argument as pydantic reads an ISO 8601 time.
func parseMoment(name string, v *string) (*time.Time, error) {
	if v == nil {
		return nil, nil
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999999", "2006-01-02"} {
		if t, err := time.Parse(layout, *v); err == nil {
			return &t, nil
		}
	}
	return nil, &toolError{fmt.Sprintf("%s: Input should be a valid datetime, got '%s'", name, *v)}
}

// streamTools is tools/streams_toolset.py.
func streamTools(s streamsapi.PlatformStreams) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List streams", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Limit  *int `json:"limit"`
				Offset int  `json:"offset"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 100
			if in.Limit != nil {
				limit = *in.Limit
			}
			if err := checkRange("limit", int64(limit), 1, 1000); err != nil {
				return nil, err
			}
			if err := checkRange("offset", int64(in.Offset), 0, maxOffset); err != nil {
				return nil, err
			}
			return s.List(ctx, c, limit, in.Offset)
		}},
		"get": {title: "Get stream", effect: effectRead, call: streamCall(s.Get)},
		"create": {title: "Create stream", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name        string `json:"name"`
				Description string `json:"description"`
			}](args)
			if err != nil {
				return nil, err
			}
			return s.Create(ctx, c, in.Name, in.Description)
		}},
		"delete": {title: "Delete stream", effect: effectDestructive, idempotent: true, openWorld: true, call: streamCall(func(ctx context.Context, c authn.Caller, id string) (any, error) {
			if err := s.Delete(ctx, c, id); err != nil {
				return nil, err
			}
			return deleted(), nil
		})},
		"list_source_types": {title: "List stream source types", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			return s.ListSourceTypes(ctx, c)
		}},
		"list_sources": {title: "List stream sources", effect: effectRead, call: streamCall(s.ListSources)},
		"create_source": {title: "Add source to stream", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID       string            `json:"stream_id"`
				SourceType     string            `json:"source_type"`
				Kind           *string           `json:"kind"`
				Credentials    map[string]any    `json:"credentials"`
				Config         map[string]string `json:"config"`
				EventTemplates map[string]any    `json:"event_templates"`
				Senders        map[string]any    `json:"senders"`
			}](args)
			if err != nil {
				return nil, err
			}
			doc := map[string]any{"source_type": in.SourceType, "kind": "webhook", "credentials": map[string]any{}, "config": map[string]string{}}
			if in.Kind != nil {
				doc["kind"] = *in.Kind
			}
			if in.Credentials != nil {
				doc["credentials"] = in.Credentials
			}
			if in.Config != nil {
				doc["config"] = in.Config
			}
			if len(in.EventTemplates) > 0 {
				doc["event_templates"] = in.EventTemplates
			}
			if len(in.Senders) > 0 {
				doc["senders"] = in.Senders
			}
			raw, err := json.Marshal(doc)
			if err != nil {
				return nil, err
			}
			return s.CreateSource(ctx, c, in.StreamID, raw)
		}},
		"update_source": {title: "Change who may write to a source", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID string          `json:"stream_id"`
				SourceID string          `json:"source_id"`
				Senders  json.RawMessage `json:"senders"`
			}](args)
			if err != nil {
				return nil, err
			}
			if len(in.Senders) == 0 || string(in.Senders) == "null" {
				return nil, &toolError{"senders: Input should be a valid dictionary"}
			}
			return s.UpdateSource(ctx, c, in.StreamID, in.SourceID, in.Senders)
		}},
		"delete_source": {title: "Remove stream source", effect: effectDestructive, idempotent: true, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID string `json:"stream_id"`
				SourceID string `json:"source_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			if err := s.DeleteSource(ctx, c, in.StreamID, in.SourceID); err != nil {
				return nil, err
			}
			return deleted(), nil
		}},
		"list_subscriptions": {title: "List stream subscriptions", effect: effectRead, call: streamCall(s.ListSubscriptions)},
		"create_forward": {title: "Create stream forward", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID    string         `json:"stream_id"`
				Outputs     []string       `json:"output_stream_ids"`
				EventFilter map[string]any `json:"event_filter"`
			}](args)
			if err != nil {
				return nil, err
			}
			return s.CreateForward(ctx, c, in.StreamID, in.Outputs, in.EventFilter)
		}},
		"delete_forward": {title: "Delete stream forward", effect: effectDestructive, idempotent: true, call: subscriptionDelete(s.DeleteForward)},
		"create_processor": {title: "Create stream processor", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID    string         `json:"stream_id"`
				Outputs     []string       `json:"output_stream_ids"`
				Code        string         `json:"code"`
				EventFilter map[string]any `json:"event_filter"`
			}](args)
			if err != nil {
				return nil, err
			}
			return s.CreateProcessor(ctx, c, in.StreamID, in.Outputs, in.Code, in.EventFilter)
		}},
		"update_processor": {title: "Update stream processor", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID       string         `json:"stream_id"`
				SubscriptionID string         `json:"subscription_id"`
				Code           *string        `json:"code"`
				Outputs        []string       `json:"output_stream_ids"`
				EventFilter    map[string]any `json:"event_filter"`
			}](args)
			if err != nil {
				return nil, err
			}
			return s.UpdateProcessor(ctx, c, in.StreamID, in.SubscriptionID, streamsapi.ProcessorChange{
				Code: in.Code, Outputs: in.Outputs, EventFilter: in.EventFilter,
			})
		}},
		"delete_processor": {title: "Delete stream processor", effect: effectDestructive, idempotent: true, call: subscriptionDelete(s.DeleteProcessor)},
		"list_events": {title: "List stream events", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				StreamID   *string `json:"stream_id"`
				After      int64   `json:"after"`
				Before     *int64  `json:"before"`
				SourceType *string `json:"source_type"`
				Kind       *string `json:"kind"`
				Sender     *string `json:"sender"`
				SessionKey *string `json:"session_key"`
				Result     *string `json:"result"`
				Since      *string `json:"since"`
				Until      *string `json:"until"`
				Limit      *int    `json:"limit"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 50
			if in.Limit != nil {
				limit = *in.Limit
			}
			if err := checkRange("limit", int64(limit), 1, 200); err != nil {
				return nil, err
			}
			if err := checkRange("after", in.After, 0, -1); err != nil {
				return nil, err
			}
			since, err := parseMoment("since", in.Since)
			if err != nil {
				return nil, err
			}
			until, err := parseMoment("until", in.Until)
			if err != nil {
				return nil, err
			}
			if in.StreamID != nil && *in.StreamID == "" {
				in.StreamID = nil
			}
			return s.ListEvents(ctx, c, streamsapi.EventQuery{
				StreamID: in.StreamID, After: in.After, Before: in.Before, SourceType: in.SourceType, Kind: in.Kind,
				Sender: in.Sender, SessionKey: in.SessionKey, Result: in.Result, Since: since, Until: until, Limit: limit,
			})
		}},
	}
}
