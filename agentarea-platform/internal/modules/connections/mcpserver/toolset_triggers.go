package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

type triggerIDArgs struct {
	TriggerID string `json:"trigger_id"`
}

// triggerCreateArgs is what create_cron and create_stream share.
type triggerCreateArgs struct {
	Name             string         `json:"name"`
	AgentID          string         `json:"agent_id"`
	Description      string         `json:"description"`
	TaskParameters   map[string]any `json:"task_parameters"`
	TaskDefinitionID *string        `json:"task_definition_id"`
	Conditions       map[string]any `json:"conditions"`
	Enabled          *bool          `json:"enabled"`
	FailureThreshold *int           `json:"failure_threshold"`
}

func (a triggerCreateArgs) create(kind string) streamsapi.TriggerCreate {
	in := streamsapi.TriggerCreate{
		Type: kind, Name: a.Name, Description: a.Description, AgentID: a.AgentID, TaskParameters: a.TaskParameters,
		TaskDefinitionID: a.TaskDefinitionID, Conditions: a.Conditions, Enabled: true, FailureThreshold: 5,
	}
	if a.Enabled != nil {
		in.Enabled = *a.Enabled
	}
	if a.FailureThreshold != nil {
		in.FailureThreshold = *a.FailureThreshold
	}
	return in
}

// triggerToggle answers {key: existed} for delete, enable and disable.
func triggerToggle(key string, f func(ctx context.Context, c authn.Caller, id string) (bool, error)) func(context.Context, authn.Caller, json.RawMessage) (any, error) {
	return func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
		in, err := decodeArgs[triggerIDArgs](args)
		if err != nil {
			return nil, err
		}
		ok, err := f(ctx, c, in.TriggerID)
		if err != nil {
			return nil, err
		}
		return map[string]any{key: ok}, nil
	}
}

// triggerTools is tools/triggers_toolset.py.
func triggerTools(t streamsapi.PlatformTriggers) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List triggers", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				AgentID    string `json:"agent_id"`
				ActiveOnly bool   `json:"active_only"`
				Limit      *int   `json:"limit"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 100
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxListed))
			return t.List(ctx, c, in.AgentID, in.ActiveOnly, limit)
		}},
		"get": {title: "Get trigger", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[triggerIDArgs](args)
			if err != nil {
				return nil, err
			}
			out, err := t.Get(ctx, c, in.TriggerID)
			if errors.Is(err, streamsapi.ErrTriggerNotFound) {
				return nil, &toolError{"Trigger not found"}
			}
			return out, err
		}},
		"create_cron": {title: "Create cron trigger", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				triggerCreateArgs
				CronExpression string  `json:"cron_expression"`
				Timezone       *string `json:"timezone"`
			}](args)
			if err != nil {
				return nil, err
			}
			create := in.create("cron")
			tz := "UTC"
			if in.Timezone != nil {
				tz = *in.Timezone
			}
			create.CronExpression, create.Timezone = &in.CronExpression, &tz
			return t.Create(ctx, c, create)
		}},
		"create_stream": {title: "Create stream trigger", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				triggerCreateArgs
				StreamID    string         `json:"stream_id"`
				EventFilter map[string]any `json:"event_filter"`
				Session     map[string]any `json:"session"`
				Batch       map[string]any `json:"batch"`
			}](args)
			if err != nil {
				return nil, err
			}
			create := in.create("stream")
			create.StreamID, create.EventFilter, create.Session, create.Batch = &in.StreamID, in.EventFilter, in.Session, in.Batch
			return t.Create(ctx, c, create)
		}},
		"delete":  {title: "Delete trigger", effect: effectDestructive, idempotent: true, call: triggerToggle("deleted", t.Delete)},
		"enable":  {title: "Enable trigger", effect: effectWrite, idempotent: true, call: triggerToggle("enabled", t.Enable)},
		"disable": {title: "Disable trigger", effect: effectWrite, idempotent: true, call: triggerToggle("disabled", t.Disable)},
		"get_history": {title: "Get trigger history", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				TriggerID string `json:"trigger_id"`
				Limit     *int   `json:"limit"`
				Offset    int    `json:"offset"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 50
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, maxPageSize))
			return t.History(ctx, c, in.TriggerID, limit, in.Offset)
		}},
	}
}
