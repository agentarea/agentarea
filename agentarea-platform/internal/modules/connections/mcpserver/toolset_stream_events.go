package mcpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

// maxStreamEventsRead is MAX_LIMIT of stream_events_toolset.py.
const maxStreamEventsRead = 200

// sinceArg is _since: an ISO 8601 time that carries its timezone.
func sinceArg(v string) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339Nano, v); err == nil {
		return t, nil
	}
	for _, layout := range []string{"2006-01-02T15:04:05.999999999", "2006-01-02T15:04", "2006-01-02"} {
		if _, err := time.Parse(layout, v); err == nil {
			return time.Time{}, &toolError{fmt.Sprintf("since must carry a timezone (e.g. Z or +03:00), got '%s'", v)}
		}
	}
	return time.Time{}, &toolError{fmt.Sprintf("since must be an ISO 8601 time, got '%s'", v)}
}

// streamEventTools is tools/stream_events_toolset.py.
func streamEventTools(e streamsapi.PlatformStreamEvents) map[string]toolDef {
	return map[string]toolDef{
		"read_stream": {title: "Read stream events", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Stream        string  `json:"stream"`
				AfterSequence int64   `json:"after_sequence"`
				Limit         *int    `json:"limit"`
				Since         *string `json:"since"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 50
			if in.Limit != nil {
				limit = *in.Limit
			}
			if limit < 1 || limit > maxStreamEventsRead {
				return nil, &toolError{fmt.Sprintf("limit must be between 1 and %d, got %d", maxStreamEventsRead, limit)}
			}
			if in.AfterSequence < 0 {
				return nil, &toolError{fmt.Sprintf("after_sequence must be at least 0, got %d", in.AfterSequence)}
			}
			var since *time.Time
			if in.Since != nil {
				t, err := sinceArg(*in.Since)
				if err != nil {
					return nil, err
				}
				since = &t
			}
			return e.Read(ctx, c, in.Stream, in.AfterSequence, limit, since)
		}},
	}
}
