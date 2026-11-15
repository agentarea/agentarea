package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
)

// ProvidersToolset is api.PlatformProviders over the models service,
// documents checked with the REST bodies' rules.
type ProvidersToolset struct {
	Svc   *service.Service
	Specs catalogapi.SpecLists
}

var _ api.PlatformProviders = ProvidersToolset{}

// refusal is the text a tool refusal carries: require_permission's and
// assert_workspace_admin's details.
func refusal(err error) error {
	switch {
	case errors.Is(err, authz.ErrDenied):
		return errors.New("Permission denied") //nolint:staticcheck // Python's detail
	case errors.Is(err, authz.ErrNotWorkspaceAdmin):
		return errors.New(authz.NotAdminDetail) //nolint:staticcheck // Python's detail
	}
	return err
}

func toolsetInput(doc map[string]any, parse func(v any, in *input, errs *[]httpx.FieldError) any) (input, error) {
	raw, err := json.Marshal(doc)
	if err != nil {
		return input{}, err
	}
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return input{}, err
	}
	in := input{ids: map[string]uuid.UUID{}}
	var errs []httpx.FieldError
	parse(v, &in, &errs)
	if err := httpx.Validation(errs...); err != nil {
		return input{}, err
	}
	return in, nil
}

func (t ProvidersToolset) ListSpecs(ctx context.Context, c authn.Caller) ([]api.ProviderSpecSummary, error) {
	specs, err := t.Specs.OfferedProviderSpecs(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	out := make([]api.ProviderSpecSummary, len(specs))
	for i, s := range specs {
		out[i] = api.ProviderSpecSummary{ID: s.ID.String(), Name: s.Name, Key: s.ProviderKey}
	}
	return out, nil
}

func (t ProvidersToolset) ListConfigs(ctx context.Context, c authn.Caller) ([]api.ProviderConfigSummary, error) {
	vs, err := t.Svc.Configs(authn.WithCaller(ctx, c), store.ConfigFilter{})
	if err != nil {
		return nil, err
	}
	out := make([]api.ProviderConfigSummary, len(vs))
	for i, v := range vs {
		out[i] = api.ProviderConfigSummary{ID: v.ID, Name: v.Name, ProviderSpecID: v.ProviderSpecID, IsActive: v.IsActive}
	}
	return out, nil
}

func (t ProvidersToolset) CreateConfig(ctx context.Context, c authn.Caller, n api.NewProviderConfig) (api.ProviderConfigRef, error) {
	doc := map[string]any{"provider_spec_id": n.ProviderSpecID, "name": n.Name, "api_key": n.APIKey, "is_public": n.IsPublic}
	if n.EndpointURL != "" {
		doc["endpoint_url"] = n.EndpointURL
	}
	if n.Description != "" {
		doc["description"] = n.Description
	}
	in, err := toolsetInput(doc, createConfigBody)
	if err != nil {
		return api.ProviderConfigRef{}, err
	}
	v, err := t.Svc.CreateConfig(authn.WithCaller(ctx, c), in.newConfig)
	if err != nil {
		return api.ProviderConfigRef{}, refusal(err)
	}
	return api.ProviderConfigRef{ID: v.ID, Name: v.Name}, nil
}

func (t ProvidersToolset) UpdateConfig(ctx context.Context, c authn.Caller, configID string, p api.ProviderConfigPatch) (api.ProviderConfigRef, error) {
	id, err := uuid.Parse(configID)
	if err != nil {
		return api.ProviderConfigRef{}, err
	}
	doc := map[string]any{}
	for k, v := range map[string]*string{"name": p.Name, "api_key": p.APIKey, "endpoint_url": p.EndpointURL, "description": p.Description} {
		if v != nil {
			doc[k] = *v
		}
	}
	for k, v := range map[string]*bool{"is_active": p.IsActive, "is_public": p.IsPublic} {
		if v != nil {
			doc[k] = *v
		}
	}
	in, err := toolsetInput(doc, updateConfigBody)
	if err != nil {
		return api.ProviderConfigRef{}, err
	}
	v, found, err := t.Svc.UpdateConfig(authn.WithCaller(ctx, c), id, in.patch)
	if err != nil {
		return api.ProviderConfigRef{}, refusal(err)
	}
	if !found {
		return api.ProviderConfigRef{}, api.ErrNotFound
	}
	return api.ProviderConfigRef{ID: v.ID, Name: v.Name}, nil
}

func (t ProvidersToolset) DeleteConfig(ctx context.Context, c authn.Caller, configID string) (bool, error) {
	id, err := uuid.Parse(configID)
	if err != nil {
		return false, err
	}
	deleted, err := t.Svc.DeleteConfig(authn.WithCaller(ctx, c), id)
	return deleted, refusal(err)
}

// ModelsToolset is api.PlatformModels over the models service.
type ModelsToolset struct {
	Svc   *service.Service
	Specs catalogapi.SpecLists
}

var _ api.PlatformModels = ModelsToolset{}

func (t ModelsToolset) ListSpecs(ctx context.Context, c authn.Caller) ([]api.ModelSpecSummary, error) {
	specs, err := t.Specs.ListModelSpecs(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	out := make([]api.ModelSpecSummary, len(specs))
	for i, s := range specs {
		name := s.DisplayName
		if name == "" {
			name = s.ModelName
		}
		out[i] = api.ModelSpecSummary{ID: s.ID.String(), Name: name, ProviderSpecID: s.ProviderSpecID.String()}
	}
	return out, nil
}

func instanceSummary(v service.InstanceView) api.ModelInstanceSummary {
	return api.ModelInstanceSummary{ID: v.ID, Name: v.Name, ModelSpecID: v.ModelSpecID, ProviderConfigID: v.ProviderConfigID, IsActive: v.IsActive}
}

func (t ModelsToolset) ListInstances(ctx context.Context, c authn.Caller) ([]api.ModelInstanceSummary, error) {
	vs, err := t.Svc.Instances(authn.WithCaller(ctx, c), service.InstanceFilter{})
	if err != nil {
		return nil, err
	}
	out := make([]api.ModelInstanceSummary, len(vs))
	for i, v := range vs {
		out[i] = instanceSummary(v)
	}
	return out, nil
}

func (t ModelsToolset) CreateInstance(ctx context.Context, c authn.Caller, n api.NewModelInstance) (api.ModelInstanceSummary, error) {
	cfg, err := uuid.Parse(n.ProviderConfigID)
	if err != nil {
		return api.ModelInstanceSummary{}, err
	}
	spec, err := uuid.Parse(n.ModelSpecID)
	if err != nil {
		return api.ModelInstanceSummary{}, err
	}
	ni := domain.NewInstance{ProviderConfigID: cfg.String(), ModelSpecID: spec.String(), Name: n.Name}
	if n.Description != "" {
		ni.Description = &n.Description
	}
	v, err := t.Svc.CreateInstance(authn.WithCaller(ctx, c), ni)
	if err != nil {
		return api.ModelInstanceSummary{}, err
	}
	return instanceSummary(v), nil
}

func (t ModelsToolset) GetInstance(ctx context.Context, c authn.Caller, id string) (api.ModelInstanceSummary, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return api.ModelInstanceSummary{}, err
	}
	v, found, err := t.Svc.Instance(authn.WithCaller(ctx, c), u)
	if err != nil {
		return api.ModelInstanceSummary{}, err
	}
	if !found {
		return api.ModelInstanceSummary{}, api.ErrNotFound
	}
	return instanceSummary(v), nil
}
