package mcpserver

import (
	"context"
	"encoding/json"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// Audit page bounds (AuditToolset.list).
const (
	auditDefaultLimit = 50
	auditMaxLimit     = 100
)

// fromISO is datetime.fromisoformat: an aware time is made naive UTC.
func fromISO(s string) (*time.Time, error) {
	if s == "" {
		return nil, nil
	}
	for _, layout := range []string{
		"2006-01-02T15:04:05.999999999Z07:00", "2006-01-02T15:04:05.999999999", "2006-01-02 15:04:05.999999999Z07:00",
		"2006-01-02 15:04:05.999999999", "2006-01-02T15:04Z07:00", "2006-01-02T15:04", "2006-01-02",
	} {
		if t, err := time.Parse(layout, s); err == nil {
			t = t.UTC()
			return &t, nil
		}
	}
	return nil, &toolError{"Invalid isoformat string: '" + s + "'"}
}

// pyISO is a naive datetime's isoformat().
func pyISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05")
	}
	return t.Format("2006-01-02T15:04:05.000000")
}

// auditTools is tools/audit_toolset.py.
func auditTools(a governanceapi.PlatformAudit) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List audit events", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Action       string `json:"action"`
				ActorID      string `json:"actor_id"`
				ResourceType string `json:"resource_type"`
				ResourceID   string `json:"resource_id"`
				Since        string `json:"since"`
				Until        string `json:"until"`
				Cursor       string `json:"cursor"`
				Limit        *int   `json:"limit"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := auditDefaultLimit
			if in.Limit != nil {
				limit = *in.Limit
			}
			limit = max(1, min(limit, auditMaxLimit))
			q := governanceapi.PlatformAuditQuery{Action: in.Action, ActorID: in.ActorID, ResourceType: in.ResourceType,
				ResourceID: in.ResourceID, Cursor: in.Cursor, Limit: limit}
			if q.Since, err = fromISO(in.Since); err != nil {
				return nil, err
			}
			if q.Until, err = fromISO(in.Until); err != nil {
				return nil, err
			}
			events, err := a.List(ctx, c, q)
			if err != nil {
				return nil, err
			}
			items := make([]map[string]any, len(events))
			for i, e := range events {
				var created any
				if !e.CreatedAt.IsZero() {
					created = pyISO(e.CreatedAt)
				}
				items[i] = map[string]any{"id": e.ID, "created_at": created, "actor_id": e.ActorID, "actor_type": e.ActorType,
					"action": e.Action, "resource_type": e.ResourceType, "resource_id": e.ResourceID, "request_id": e.RequestID}
			}
			var next any
			if len(events) == limit {
				next = events[len(events)-1].ID
			}
			return map[string]any{"events": items, "next_cursor": next}, nil
		}},
	}
}
