package handlers

import (
	"context"
	"errors"
	"io/fs"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/models"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	catalogapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/models/store"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve/static"
)

// Server implements the provider-configs, model-instances and pricing routes.
type Server struct {
	svc *service.Service
	// Icons is static/icons/providers, the files served at /static/icons/providers.
	Icons fs.FS
}

var _ gen.StrictServerInterface = (*Server)(nil)

// New builds the server.
func New(svc *service.Service) *Server {
	return &Server{svc: svc, Icons: static.ProviderIcons()}
}

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var nf *service.NotFoundError
	var br *service.BadRequestError
	var he *service.HTTPError
	var pm *service.PlatformManagedError
	var unpriced *catalogapi.ModelPricingNotConfiguredError
	switch {
	case errors.As(err, &pm):
		return httpx.Forbidden(pm.Error()), true
	case errors.As(err, &nf):
		return httpx.NotFound(nf.Detail), true
	case errors.As(err, &br):
		return httpx.BadRequest(br.Detail), true
	case errors.As(err, &he):
		return httpx.HTTPError(he.Status, he.Detail), true
	case errors.As(err, &unpriced):
		return httpx.NewError(http.StatusUnprocessableEntity, "model_pricing_not_configured", unpriced.Error()), true
	}
	return nil, false
}

func utc(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05") + "Z"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "Z"
}

func orNil[T any](p *T) any {
	if p == nil {
		return nil
	}
	return *p
}

func configJSON(v service.ConfigView) wirejson.Object {
	var endpoint any
	if !v.PlatformManaged() {
		endpoint = orNil(v.EndpointURL)
	}
	requiresKey := true
	var specName, specKey any
	if v.Spec != nil {
		requiresKey = v.Spec.RequiresAPIKey
		specName, specKey = v.Spec.Name, v.Spec.ProviderKey
	}
	ids := make([]any, len(v.ModelSpecIDs))
	for i, id := range v.ModelSpecIDs {
		ids[i] = id
	}
	return wirejson.Object{
		{Key: "id", Value: v.ID},
		{Key: "provider_spec_id", Value: v.ProviderSpecID},
		{Key: "name", Value: v.Name},
		{Key: "endpoint_url", Value: endpoint},
		{Key: "workspace_id", Value: v.WorkspaceID},
		{Key: "created_by", Value: v.CreatedBy},
		{Key: "is_active", Value: v.IsActive},
		{Key: "is_public", Value: v.IsPublic},
		{Key: "created_at", Value: utc(v.CreatedAt)},
		{Key: "updated_at", Value: utc(v.UpdatedAt)},
		{Key: "managed_by", Value: orNil(v.ManagedBy)},
		{Key: "requires_api_key", Value: requiresKey},
		{Key: "provider_spec_name", Value: specName},
		{Key: "provider_spec_key", Value: specKey},
		{Key: "model_instance_ids", Value: ids},
	}
}

func configsJSON(vs []service.ConfigView) []any {
	out := make([]any, len(vs))
	for i, v := range vs {
		out[i] = configJSON(v)
	}
	return out
}

func instanceJSON(v service.InstanceView) wirejson.Object {
	var provName, provKey, modelName, modelDisplay, modelKind, configName, managedBy any
	if v.Provider != nil {
		provName, provKey = v.Provider.Name, v.Provider.ProviderKey
	}
	if v.Model != nil {
		modelName, modelDisplay, modelKind = v.Model.ModelName, v.Model.DisplayName, v.Model.Kind
	}
	if v.Config != nil {
		configName, managedBy = v.Config.Name, orNil(v.Config.ManagedBy)
	}
	tags := make([]any, len(v.Tags))
	for i, t := range v.Tags {
		tags[i] = t
	}
	return wirejson.Object{
		{Key: "id", Value: v.ID},
		{Key: "provider_config_id", Value: v.ProviderConfigID},
		{Key: "model_spec_id", Value: v.ModelSpecID},
		{Key: "name", Value: v.Name},
		{Key: "description", Value: orNil(v.Description)},
		{Key: "is_active", Value: v.IsActive},
		{Key: "is_public", Value: v.IsPublic},
		{Key: "created_at", Value: utc(v.CreatedAt)},
		{Key: "updated_at", Value: utc(v.UpdatedAt)},
		{Key: "provider_name", Value: provName},
		{Key: "provider_key", Value: provKey},
		{Key: "provider_icon_url", Value: orNil(v.IconURL)},
		{Key: "model_name", Value: modelName},
		{Key: "model_display_name", Value: modelDisplay},
		{Key: "model_kind", Value: modelKind},
		{Key: "config_name", Value: configName},
		{Key: "managed_by", Value: managedBy},
		{Key: "tags", Value: tags},
	}
}

func moneyOrNil(d *money.Decimal) any {
	if d == nil {
		return nil
	}
	return d.String()
}

func discoveryJSON(d service.Discovery, withID bool) wirejson.Object {
	models := make([]any, len(d.Models))
	for i, m := range d.Models {
		display := m.DisplayName
		if display == "" {
			display = m.ModelName
		}
		var desc any
		if m.Description != nil && *m.Description != "" {
			desc = *m.Description
		}
		o := wirejson.Object{}
		if withID {
			o = append(o, wirejson.Member{Key: "id", Value: m.ID})
		}
		o = append(o,
			wirejson.Member{Key: "model_name", Value: m.ModelName},
			wirejson.Member{Key: "display_name", Value: display},
			wirejson.Member{Key: "kind", Value: m.Kind},
			wirejson.Member{Key: "context_window", Value: orNil(m.ContextWindow)},
			wirejson.Member{Key: "max_output_tokens", Value: orNil(m.MaxOutputTokens)},
			wirejson.Member{Key: "input_cost_per_token", Value: moneyOrNil(m.Input)},
			wirejson.Member{Key: "output_cost_per_token", Value: moneyOrNil(m.Output)},
			wirejson.Member{Key: "cached_input_cost_per_token", Value: moneyOrNil(m.CachedInput)},
			wirejson.Member{Key: "cache_creation_input_cost_per_token", Value: moneyOrNil(m.CacheCreation)},
			wirejson.Member{Key: "supports_function_calling", Value: m.SupportsFunctionCalling},
			wirejson.Member{Key: "supports_vision", Value: m.SupportsVision},
			wirejson.Member{Key: "supports_reasoning", Value: m.SupportsReasoning},
			wirejson.Member{Key: "description", Value: desc},
			wirejson.Member{Key: "is_new", Value: m.IsNew},
		)
		models[i] = o
	}
	skipped := make([]any, len(d.Skipped))
	for i, s := range d.Skipped {
		miss := make([]any, len(s.Missing))
		for j, m := range s.Missing {
			miss[j] = m
		}
		skipped[i] = wirejson.Object{{Key: "model_name", Value: s.ModelName}, {Key: "missing", Value: miss}}
	}
	return wirejson.Object{
		{Key: "discovered", Value: len(d.Models)},
		{Key: "new_models", Value: d.New},
		{Key: "models", Value: models},
		{Key: "skipped", Value: skipped},
	}
}

func ok(body any) response { return response{status: http.StatusOK, body: body} }

func (s *Server) GetPricingCurrencyV1PricingCurrencyGet(context.Context, gen.GetPricingCurrencyV1PricingCurrencyGetRequestObject) (gen.GetPricingCurrencyV1PricingCurrencyGetResponseObject, error) {
	return ok(wirejson.Object{{Key: "currency", Value: string(s.svc.Currency())}}), nil
}

func (s *Server) ListProviderConfigsV1ProviderConfigsGet(ctx context.Context, _ gen.ListProviderConfigsV1ProviderConfigsGetRequestObject) (gen.ListProviderConfigsV1ProviderConfigsGetResponseObject, error) {
	in := inputFrom(ctx)
	vs, err := s.svc.Configs(ctx, store.ConfigFilter{ProviderSpecID: in.specID, IsActive: in.isActive})
	if err != nil {
		return nil, err
	}
	return ok(configsJSON(vs)), nil
}

func (s *Server) ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGet(ctx context.Context, _ gen.ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetRequestObject) (gen.ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGetResponseObject, error) {
	in := inputFrom(ctx)
	vs, err := s.svc.Configs(ctx, store.ConfigFilter{ProviderSpecID: in.specID, IsActive: in.isActive})
	if err != nil {
		return nil, err
	}
	return ok(configsJSON(vs)), nil
}

func (s *Server) CreateProviderConfigV1ProviderConfigsPost(ctx context.Context, _ gen.CreateProviderConfigV1ProviderConfigsPostRequestObject) (gen.CreateProviderConfigV1ProviderConfigsPostResponseObject, error) {
	v, err := s.svc.CreateConfig(ctx, inputFrom(ctx).newConfig)
	if err != nil {
		return nil, err
	}
	return ok(configJSON(v)), nil
}

func configNotFound() error {
	return &service.HTTPError{Status: http.StatusNotFound, Detail: "Provider configuration not found"}
}

func (s *Server) GetProviderConfigV1ProviderConfigsConfigIdGet(ctx context.Context, r gen.GetProviderConfigV1ProviderConfigsConfigIdGetRequestObject) (gen.GetProviderConfigV1ProviderConfigsConfigIdGetResponseObject, error) {
	v, found, err := s.svc.Config(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, configNotFound()
	}
	return ok(configJSON(v)), nil
}

func (s *Server) update(ctx context.Context, id uuid.UUID) (response, error) {
	v, found, err := s.svc.UpdateConfig(ctx, id, inputFrom(ctx).patch)
	if err != nil {
		return response{}, err
	}
	if !found {
		return response{}, configNotFound()
	}
	return ok(configJSON(v)), nil
}

func (s *Server) UpdateProviderConfigV1ProviderConfigsConfigIdPut(ctx context.Context, r gen.UpdateProviderConfigV1ProviderConfigsConfigIdPutRequestObject) (gen.UpdateProviderConfigV1ProviderConfigsConfigIdPutResponseObject, error) {
	resp, err := s.update(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

func (s *Server) PatchProviderConfigV1ProviderConfigsConfigIdPatch(ctx context.Context, r gen.PatchProviderConfigV1ProviderConfigsConfigIdPatchRequestObject) (gen.PatchProviderConfigV1ProviderConfigsConfigIdPatchResponseObject, error) {
	resp, err := s.update(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	return resp, nil
}

func (s *Server) DeleteProviderConfigV1ProviderConfigsConfigIdDelete(ctx context.Context, r gen.DeleteProviderConfigV1ProviderConfigsConfigIdDeleteRequestObject) (gen.DeleteProviderConfigV1ProviderConfigsConfigIdDeleteResponseObject, error) {
	deleted, err := s.svc.DeleteConfig(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	if !deleted {
		return nil, configNotFound()
	}
	return ok(wirejson.Object{{Key: "message", Value: "Provider configuration deleted successfully"}}), nil
}

func (s *Server) DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPost(ctx context.Context, _ gen.DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostRequestObject) (gen.DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPostResponseObject, error) {
	in := inputFrom(ctx)
	d, err := s.svc.DiscoverPreview(ctx, in.providerKey, in.apiKey, in.endpointURL)
	if err != nil {
		return nil, err
	}
	return ok(discoveryJSON(d, true)), nil
}

func (s *Server) DiscoverModelsV1ProviderConfigsConfigIdDiscoverPost(ctx context.Context, r gen.DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostRequestObject) (gen.DiscoverModelsV1ProviderConfigsConfigIdDiscoverPostResponseObject, error) {
	d, err := s.svc.DiscoverConfig(ctx, r.ConfigId)
	if err != nil {
		return nil, err
	}
	return ok(discoveryJSON(d, false)), nil
}

var providerKeyPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]+$`)

func (s *Server) GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGet(_ context.Context, r gen.GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetRequestObject) (gen.GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGetResponseObject, error) {
	if !providerKeyPattern.MatchString(r.ProviderKey) {
		return nil, &service.HTTPError{Status: http.StatusBadRequest, Detail: "Invalid provider key"}
	}
	notFound := &service.HTTPError{Status: http.StatusNotFound, Detail: "Provider logo not found"}
	for _, name := range []string{strings.ToLower(r.ProviderKey) + ".svg", "default.svg"} {
		if st, err := fs.Stat(s.Icons, name); err != nil || !st.Mode().IsRegular() {
			continue
		}
		raw, err := fs.ReadFile(s.Icons, name)
		if err != nil {
			return nil, err
		}
		return response{status: http.StatusOK, raw: raw, headers: map[string]string{
			"Content-Type": "image/svg+xml", "Cache-Control": "public, max-age=3600",
		}}, nil
	}
	return nil, notFound
}

func (s *Server) ListModelInstancesV1ModelInstancesGet(ctx context.Context, _ gen.ListModelInstancesV1ModelInstancesGetRequestObject) (gen.ListModelInstancesV1ModelInstancesGetResponseObject, error) {
	in := inputFrom(ctx)
	vs, err := s.svc.Instances(ctx, service.InstanceFilter{
		InstanceFilter: store.InstanceFilter{ProviderConfigID: in.configID, ModelSpecID: in.modelSpecID, IsActive: in.isActive},
		Kind:           in.kind,
	})
	if err != nil {
		return nil, err
	}
	out := make([]any, len(vs))
	for i, v := range vs {
		out[i] = instanceJSON(v)
	}
	return ok(out), nil
}

func (s *Server) CreateModelInstanceV1ModelInstancesPost(ctx context.Context, _ gen.CreateModelInstanceV1ModelInstancesPostRequestObject) (gen.CreateModelInstanceV1ModelInstancesPostResponseObject, error) {
	v, err := s.svc.CreateInstance(ctx, inputFrom(ctx).newInstance)
	if err != nil {
		return nil, err
	}
	return ok(instanceJSON(v)), nil
}

func (s *Server) CreateModelInstancesBulkV1ModelInstancesBulkPost(ctx context.Context, _ gen.CreateModelInstancesBulkV1ModelInstancesBulkPostRequestObject) (gen.CreateModelInstancesBulkV1ModelInstancesBulkPostResponseObject, error) {
	done, failed, err := s.svc.CreateInstances(ctx, inputFrom(ctx).bulk)
	if err != nil {
		return nil, err
	}
	succeeded := make([]any, len(done))
	for i, v := range done {
		succeeded[i] = instanceJSON(v)
	}
	fails := make([]any, len(failed))
	for i, f := range failed {
		fails[i] = wirejson.Object{{Key: "index", Value: f.Index}, {Key: "model_spec_id", Value: f.ModelSpecID}, {Key: "error", Value: f.Error}}
	}
	return ok(wirejson.Object{
		{Key: "succeeded", Value: succeeded},
		{Key: "failed", Value: fails},
		{Key: "succeeded_count", Value: len(done)},
		{Key: "failed_count", Value: len(failed)},
	}), nil
}

func (s *Server) ValidateModelInstanceV1ModelInstancesTestPost(ctx context.Context, _ gen.ValidateModelInstanceV1ModelInstancesTestPostRequestObject) (gen.ValidateModelInstanceV1ModelInstancesTestPostResponseObject, error) {
	in := inputFrom(ctx)
	r, err := s.svc.TestModel(ctx, in.testConfig, in.testSpec, in.testMessage)
	if err != nil {
		return nil, err
	}
	return ok(wirejson.Object{
		{Key: "success", Value: r.Success},
		{Key: "message", Value: r.Message},
		{Key: "response_content", Value: orNil(r.ResponseContent)},
		{Key: "error_type", Value: orNil(r.ErrorType)},
		{Key: "provider_type", Value: orNil(r.ProviderType)},
		{Key: "model_name", Value: orNil(r.ModelName)},
		{Key: "cost", Value: moneyOrNil(r.Cost)},
		{Key: "currency", Value: "USD"},
		{Key: "tokens_used", Value: orNil(r.TokensUsed)},
	}), nil
}

func instanceNotFound() error {
	return &service.HTTPError{Status: http.StatusNotFound, Detail: "Model instance not found"}
}

func (s *Server) GetModelInstanceV1ModelInstancesInstanceIdGet(ctx context.Context, r gen.GetModelInstanceV1ModelInstancesInstanceIdGetRequestObject) (gen.GetModelInstanceV1ModelInstancesInstanceIdGetResponseObject, error) {
	v, found, err := s.svc.Instance(ctx, r.InstanceId)
	if err != nil {
		return nil, err
	}
	if !found {
		return nil, instanceNotFound()
	}
	return ok(instanceJSON(v)), nil
}

func (s *Server) DeleteModelInstanceV1ModelInstancesInstanceIdDelete(ctx context.Context, r gen.DeleteModelInstanceV1ModelInstancesInstanceIdDeleteRequestObject) (gen.DeleteModelInstanceV1ModelInstancesInstanceIdDeleteResponseObject, error) {
	deleted, err := s.svc.DeleteInstance(ctx, r.InstanceId)
	if err != nil {
		return nil, err
	}
	if !deleted {
		return nil, instanceNotFound()
	}
	return ok(wirejson.Object{{Key: "message", Value: "Model instance deleted successfully"}}), nil
}
