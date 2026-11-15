package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
)

func modelInstanceOut(m modelsapi.ModelInstanceSummary) map[string]any {
	return map[string]any{
		"id": m.ID, "name": m.Name, "model_spec_id": m.ModelSpecID,
		"provider_config_id": m.ProviderConfigID, "is_active": m.IsActive,
	}
}

// modelTools is tools/models_toolset.py.
func modelTools(m modelsapi.PlatformModels) map[string]toolDef {
	return map[string]toolDef{
		"list_specs": {title: "List model specs", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			specs, err := m.ListSpecs(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(specs))
			for i, s := range specs {
				out[i] = map[string]any{"id": s.ID, "name": s.Name, "provider_spec_id": s.ProviderSpecID}
			}
			return out, nil
		}},
		"list_instances": {title: "List model instances", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			instances, err := m.ListInstances(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(instances))
			for i, s := range instances {
				out[i] = modelInstanceOut(s)
			}
			return out, nil
		}},
		"create_instance": {title: "Create model instance", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ProviderConfigID string `json:"provider_config_id"`
				ModelSpecID      string `json:"model_spec_id"`
				Name             string `json:"name"`
				Description      string `json:"description"`
			}](args)
			if err != nil {
				return nil, err
			}
			inst, err := m.CreateInstance(ctx, c, modelsapi.NewModelInstance{
				ProviderConfigID: in.ProviderConfigID, ModelSpecID: in.ModelSpecID, Name: in.Name, Description: in.Description,
			})
			if err != nil {
				return nil, err
			}
			return modelInstanceOut(inst), nil
		}},
		"get": {title: "Get model instance", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ModelInstanceID string `json:"model_instance_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			inst, err := m.GetInstance(ctx, c, in.ModelInstanceID)
			if errors.Is(err, modelsapi.ErrNotFound) {
				return nil, &toolError{"Model instance not found"}
			}
			if err != nil {
				return nil, err
			}
			return modelInstanceOut(inst), nil
		}},
	}
}
