package handlers

import (
	"context"
	"net/http"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/catalog"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service"
)

func moneyOrNil(d *money.Decimal) any {
	if d == nil {
		return nil
	}
	return d.String()
}

// specModelJSON is provider_specs.py's ModelSpecResponse.
func specModelJSON(m api.ModelSpec) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: m.ID.String()},
		{Key: "provider_spec_id", Value: m.ProviderSpecID.String()},
		{Key: "model_name", Value: m.ModelName},
		{Key: "display_name", Value: m.DisplayName},
		{Key: "description", Value: orNil(m.Description)},
		{Key: "kind", Value: m.Kind},
		{Key: "context_window", Value: orNil(m.ContextWindow)},
		{Key: "max_output_tokens", Value: orNil(m.MaxOutputTokens)},
		{Key: "input_cost_per_token", Value: moneyOrNil(m.InputCostPerToken)},
		{Key: "output_cost_per_token", Value: moneyOrNil(m.OutputCostPerToken)},
		{Key: "cached_input_cost_per_token", Value: moneyOrNil(m.CachedInputCostPerToken)},
		{Key: "cache_creation_input_cost_per_token", Value: moneyOrNil(m.CacheCreationInputCostPerToken)},
		{Key: "supports_function_calling", Value: orNil(m.SupportsFunctionCalling)},
		{Key: "supports_vision", Value: orNil(m.SupportsVision)},
		{Key: "supports_reasoning", Value: orNil(m.SupportsReasoning)},
		{Key: "is_active", Value: m.IsActive},
		{Key: "created_at", Value: utcISO(m.CreatedAt)},
		{Key: "updated_at", Value: utcISO(m.UpdatedAt)},
	}
}

// providerJSON is ProviderSpecResponse, with models when withModels.
func providerJSON(p service.ProviderView, withModels bool) wirejson.Object {
	o := wirejson.Object{
		{Key: "id", Value: p.ID.String()},
		{Key: "provider_key", Value: p.ProviderKey},
		{Key: "name", Value: p.Name},
		{Key: "description", Value: orNil(p.Description)},
		{Key: "provider_type", Value: p.ProviderType},
		{Key: "icon", Value: orNil(p.Icon)},
		{Key: "icon_url", Value: orNil(p.IconURL)},
		{Key: "is_builtin", Value: p.IsBuiltin},
		{Key: "is_first_party", Value: p.IsFirstParty},
		{Key: "created_at", Value: utcISO(p.CreatedAt)},
		{Key: "updated_at", Value: utcISO(p.UpdatedAt)},
	}
	if withModels {
		models := make([]any, len(p.Models))
		for i, m := range p.Models {
			models[i] = specModelJSON(m)
		}
		o = append(o, wirejson.Member{Key: "models", Value: models})
	}
	return o
}

// modelJSON is model_specs.py's ModelSpecResponse.
func modelJSON(v service.ModelView) wirejson.Object {
	return wirejson.Object{
		{Key: "id", Value: v.ID.String()},
		{Key: "provider_spec_id", Value: v.ProviderSpecID.String()},
		{Key: "model_name", Value: v.ModelName},
		{Key: "display_name", Value: v.DisplayName},
		{Key: "description", Value: orNil(v.Description)},
		{Key: "kind", Value: v.Kind},
		{Key: "context_window", Value: orNil(v.ContextWindow)},
		{Key: "max_output_tokens", Value: orNil(v.MaxOutputTokens)},
		{Key: "input_cost_per_token", Value: moneyOrNil(v.InputCostPerToken)},
		{Key: "output_cost_per_token", Value: moneyOrNil(v.OutputCostPerToken)},
		{Key: "cached_input_cost_per_token", Value: moneyOrNil(v.CachedInputCostPerToken)},
		{Key: "cache_creation_input_cost_per_token", Value: moneyOrNil(v.CacheCreationInputCostPerToken)},
		{Key: "supports_function_calling", Value: orNil(v.SupportsFunctionCalling)},
		{Key: "supports_vision", Value: orNil(v.SupportsVision)},
		{Key: "supports_reasoning", Value: orNil(v.SupportsReasoning)},
		{Key: "default_context_strategy", Value: orNil(v.DefaultContextStrategy)},
		{Key: "is_active", Value: v.IsActive},
		{Key: "created_at", Value: utcISO(v.CreatedAt)},
		{Key: "updated_at", Value: utcISO(v.UpdatedAt)},
		{Key: "provider_name", Value: orNil(v.ProviderName)},
		{Key: "provider_key", Value: orNil(v.ProviderKey)},
	}
}

func modelsJSON(vs []service.ModelView) []any {
	out := make([]any, len(vs))
	for i, v := range vs {
		out[i] = modelJSON(v)
	}
	return out
}

func (s *Server) providers(ctx context.Context, withModels bool) (response, error) {
	c, err := caller(ctx)
	if err != nil {
		return response{}, err
	}
	ps, err := s.svc.ProviderSpecs(ctx, c.Workspace, inputFrom(ctx).isBuiltin)
	if err != nil {
		return response{}, err
	}
	out := make([]any, len(ps))
	for i, p := range ps {
		out[i] = providerJSON(p, withModels)
	}
	return ok(out), nil
}

func (s *Server) ListProviderSpecsV1ProviderSpecsGet(ctx context.Context, _ gen.ListProviderSpecsV1ProviderSpecsGetRequestObject) (gen.ListProviderSpecsV1ProviderSpecsGetResponseObject, error) {
	r, err := s.providers(ctx, false)
	if err != nil {
		return nil, err
	}
	return r, nil
}

func (s *Server) ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGet(ctx context.Context, _ gen.ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetRequestObject) (gen.ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGetResponseObject, error) {
	r, err := s.providers(ctx, true)
	if err != nil {
		return nil, err
	}
	return r, nil
}

func (s *Server) provider(ctx context.Context, id uuid.UUID, key string, byKey bool) (response, error) {
	c, err := caller(ctx)
	if err != nil {
		return response{}, err
	}
	p, found, err := s.svc.ProviderSpecWithModels(ctx, c.Workspace, id, key, byKey)
	if err != nil {
		return response{}, err
	}
	if !found {
		return response{}, service.ErrProviderNotFound()
	}
	return ok(providerJSON(p, true)), nil
}

func (s *Server) GetProviderSpecV1ProviderSpecsProviderSpecIdGet(ctx context.Context, rq gen.GetProviderSpecV1ProviderSpecsProviderSpecIdGetRequestObject) (gen.GetProviderSpecV1ProviderSpecsProviderSpecIdGetResponseObject, error) {
	r, err := s.provider(ctx, rq.ProviderSpecId, "", false)
	if err != nil {
		return nil, err
	}
	return r, nil
}

func (s *Server) GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGet(ctx context.Context, rq gen.GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetRequestObject) (gen.GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGetResponseObject, error) {
	r, err := s.provider(ctx, uuid.Nil, rq.ProviderKey, true)
	if err != nil {
		return nil, err
	}
	return r, nil
}

func (s *Server) ListModelSpecsV1ModelSpecsGet(ctx context.Context, _ gen.ListModelSpecsV1ModelSpecsGetRequestObject) (gen.ListModelSpecsV1ModelSpecsGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	vs, err := s.svc.ModelSpecs(ctx, c.Workspace, inputFrom(ctx).modelFilter)
	if err != nil {
		return nil, err
	}
	return ok(modelsJSON(vs)), nil
}

func (s *Server) ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGet(ctx context.Context, rq gen.ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetRequestObject) (gen.ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	f := inputFrom(ctx).modelFilter
	id := rq.ProviderSpecId
	f.ProviderSpecID = &id
	vs, err := s.svc.ModelSpecs(ctx, c.Workspace, f)
	if err != nil {
		return nil, err
	}
	return ok(modelsJSON(vs)), nil
}

func (s *Server) GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGet(ctx context.Context, rq gen.GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetRequestObject) (gen.GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, found, err := s.svc.ModelSpecByName(ctx, c.Workspace, rq.ProviderSpecId, rq.ModelName)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, &service.NotFoundError{Detail: "Model specification '" + rq.ModelName + "' not found for provider"}
	}
	return ok(modelJSON(v)), nil
}

func (s *Server) GetModelSpecV1ModelSpecsModelSpecIdGet(ctx context.Context, rq gen.GetModelSpecV1ModelSpecsModelSpecIdGetRequestObject) (gen.GetModelSpecV1ModelSpecsModelSpecIdGetResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, found, err := s.svc.ModelSpec(ctx, c.Workspace, rq.ModelSpecId)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrModelSpecNotFound()
	}
	return ok(modelJSON(v)), nil
}

func (s *Server) CreateModelSpecV1ModelSpecsPost(ctx context.Context, _ gen.CreateModelSpecV1ModelSpecsPostRequestObject) (gen.CreateModelSpecV1ModelSpecsPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.CreateModelSpec(ctx, c.Workspace, c.UserID, inputFrom(ctx).newModel)
	if err != nil {
		return nil, err
	}
	return ok(modelJSON(v)), nil
}

func (s *Server) UpsertModelSpecV1ModelSpecsUpsertPost(ctx context.Context, _ gen.UpsertModelSpecV1ModelSpecsUpsertPostRequestObject) (gen.UpsertModelSpecV1ModelSpecsUpsertPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.UpsertModelSpec(ctx, c.Workspace, c.UserID, inputFrom(ctx).newModel)
	if err != nil {
		return nil, err
	}
	return ok(modelJSON(v)), nil
}

func (s *Server) UpdateModelSpecV1ModelSpecsModelSpecIdPatch(ctx context.Context, rq gen.UpdateModelSpecV1ModelSpecsModelSpecIdPatchRequestObject) (gen.UpdateModelSpecV1ModelSpecsModelSpecIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	v, err := s.svc.UpdateModelSpec(ctx, c.Workspace, rq.ModelSpecId, inputFrom(ctx).modelFields)
	if err != nil {
		return nil, err
	}
	return ok(modelJSON(v)), nil
}

func (s *Server) DeleteModelSpecV1ModelSpecsModelSpecIdDelete(ctx context.Context, rq gen.DeleteModelSpecV1ModelSpecsModelSpecIdDeleteRequestObject) (gen.DeleteModelSpecV1ModelSpecsModelSpecIdDeleteResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.DeleteModelSpec(ctx, c.Workspace, rq.ModelSpecId); err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "message", Value: "Model specification deleted successfully"}}), nil
}

func (s *Server) UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePost(ctx context.Context, rq gen.UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostRequestObject) (gen.UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.svc.UpdateItemSpec(ctx, c.Workspace, rq.ItemId.String()); err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "status", Value: "updated"}}), nil
}

func (s *Server) UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPost(ctx context.Context, rq gen.UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostRequestObject) (gen.UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	updated, failed, err := s.svc.UpdateAllSpecs(ctx, c.Workspace, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{{Key: "updated", Value: updated}, {Key: "errors", Value: failed}}), nil
}

func (s *Server) CreateWorkspaceRegistryV1WorkspaceRegistriesPost(ctx context.Context, _ gen.CreateWorkspaceRegistryV1WorkspaceRegistriesPostRequestObject) (gen.CreateWorkspaceRegistryV1WorkspaceRegistriesPostResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	n := inputFrom(ctx).registry
	ws := c.Workspace.ID()
	n.WorkspaceID = &ws
	r, err := s.svc.CreateWorkspaceRegistry(ctx, c, n)
	if err != nil {
		return nil, err
	}
	return response{status: http.StatusCreated, body: registryJSON(r)}, nil
}

func (s *Server) UpdateWorkspaceRegistryV1WorkspaceRegistriesRegistryIdPatch(ctx context.Context, rq gen.UpdateWorkspaceRegistryV1WorkspaceRegistriesRegistryIdPatchRequestObject) (gen.UpdateWorkspaceRegistryV1WorkspaceRegistriesRegistryIdPatchResponseObject, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	current, found, err := s.svc.WorkspaceRegistry(ctx, c.Workspace, rq.RegistryId.String())
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, service.ErrRegistryNotFound()
	}
	p := inputFrom(ctx).registryPatch
	if p.Empty() {
		return nil, service.ErrNoFields()
	}
	r, err := s.svc.UpdateWorkspaceRegistry(ctx, c, current, p)
	if err != nil {
		return nil, err
	}
	return ok(registryJSON(r)), nil
}
