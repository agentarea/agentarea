package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	governanceapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// secretTools is tools/secrets_toolset.py.
func secretTools(s governanceapi.PlatformSecrets) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List secrets", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			list, err := s.ListOwn(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(list))
			for i, sec := range list {
				out[i] = map[string]any{"id": sec.ID, "name": sec.Name, "description": sec.Description}
			}
			return out, nil
		}},
		"create": {title: "Create secret", effect: effectPrivileged, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name        string  `json:"name"`
				Value       string  `json:"value"`
				Description *string `json:"description"`
			}](args)
			if err != nil {
				return nil, err
			}
			sec, err := s.Create(ctx, c, in.Name, in.Value, in.Description)
			if err != nil {
				return nil, err
			}
			return map[string]any{"created": true, "id": sec.ID, "name": in.Name}, nil
		}},
		"delete": {title: "Delete secret", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name string `json:"name"`
			}](args)
			if err != nil {
				return nil, err
			}
			if err := s.DeleteByName(ctx, c, in.Name); err != nil {
				if errors.Is(err, governanceapi.ErrNoSuchSecret) {
					return nil, &toolError{err.Error()}
				}
				return nil, err
			}
			return map[string]any{"deleted": true, "name": in.Name}, nil
		}},
	}
}
