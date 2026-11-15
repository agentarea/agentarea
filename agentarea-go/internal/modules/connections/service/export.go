package service

import (
	"context"
	"fmt"
	"sort"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
)

var _ api.MCPExports = (*Service)(nil)

// ExportInstances is the instance list the workspace config export reads.
func (s *Service) ExportInstances(ctx context.Context, c authn.Caller) ([]api.ExportInstance, error) {
	rows, _, err := s.listInstances(ctx, c)
	if err != nil {
		return nil, err
	}
	out := make([]api.ExportInstance, 0, len(rows))
	for _, inst := range rows {
		e := api.ExportInstance{ID: inst.ID, Name: inst.Name, Platform: inst.PlatformManaged(), EnvVars: inst.EnvVars()}
		if !e.Platform {
			spec, ok, err := s.serverSpec(ctx, c.Workspace, inst)
			if err != nil {
				return nil, err
			}
			if !ok {
				return nil, fmt.Errorf("MCP server spec %s not found", inst.ServerSpecID)
			}
			e.Spec = exportObject(transportSpec(spec, inst))
			e.ContextSigning = inst.JSONSpec["context_signing"] == true
		}
		out = append(out, e)
	}
	return out, nil
}

// exportObject is a spec as an object with its keys sorted at every level.
func exportObject(m map[string]any) wirejson.Object {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make(wirejson.Object, 0, len(keys))
	for _, k := range keys {
		out = append(out, wirejson.Member{Key: k, Value: exportValue(m[k])})
	}
	return out
}

func exportValue(v any) any {
	switch x := v.(type) {
	case map[string]any:
		return exportObject(x)
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = exportValue(e)
		}
		return out
	}
	return v
}
