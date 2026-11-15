package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	modelsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
)

type configIDArgs struct {
	ConfigID string `json:"config_id"`
}

// providerTools is tools/providers_toolset.py.
func providerTools(p modelsapi.PlatformProviders) map[string]toolDef {
	return map[string]toolDef{
		"list_specs": {title: "List LLM provider specs", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			specs, err := p.ListSpecs(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(specs))
			for i, s := range specs {
				out[i] = map[string]any{"id": s.ID, "name": s.Name, "key": s.Key}
			}
			return out, nil
		}},
		"list_configs": {title: "List LLM provider configs", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			configs, err := p.ListConfigs(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(configs))
			for i, s := range configs {
				out[i] = map[string]any{"id": s.ID, "name": s.Name, "provider_spec_id": s.ProviderSpecID, "is_active": s.IsActive}
			}
			return out, nil
		}},
		"create_config": {title: "Create LLM provider config", effect: effectPrivileged, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ProviderSpecID string `json:"provider_spec_id"`
				Name           string `json:"name"`
				APIKey         string `json:"api_key"`
				EndpointURL    string `json:"endpoint_url"`
				Description    string `json:"description"`
				IsPublic       bool   `json:"is_public"`
			}](args)
			if err != nil {
				return nil, err
			}
			ref, err := p.CreateConfig(ctx, c, modelsapi.NewProviderConfig{
				ProviderSpecID: in.ProviderSpecID, Name: in.Name, APIKey: in.APIKey,
				EndpointURL: in.EndpointURL, Description: in.Description, IsPublic: in.IsPublic,
			})
			if err != nil {
				return nil, err
			}
			return map[string]any{"id": ref.ID, "name": ref.Name}, nil
		}},
		"update_config": {title: "Update LLM provider config", effect: effectPrivileged, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ConfigID    string  `json:"config_id"`
				Name        *string `json:"name"`
				APIKey      *string `json:"api_key"`
				EndpointURL *string `json:"endpoint_url"`
				Description *string `json:"description"`
				IsActive    *bool   `json:"is_active"`
				IsPublic    *bool   `json:"is_public"`
			}](args)
			if err != nil {
				return nil, err
			}
			ref, err := p.UpdateConfig(ctx, c, in.ConfigID, modelsapi.ProviderConfigPatch{
				Name: in.Name, APIKey: in.APIKey, EndpointURL: in.EndpointURL, Description: in.Description,
				IsActive: in.IsActive, IsPublic: in.IsPublic,
			})
			if errors.Is(err, modelsapi.ErrNotFound) {
				return nil, &toolError{"Provider configuration not found"}
			}
			if err != nil {
				return nil, err
			}
			return map[string]any{"id": ref.ID, "name": ref.Name}, nil
		}},
		"delete_config": {title: "Delete LLM provider config", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[configIDArgs](args)
			if err != nil {
				return nil, err
			}
			deleted, err := p.DeleteConfig(ctx, c, in.ConfigID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"deleted": deleted}, nil
		}},
	}
}
