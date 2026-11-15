package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/models"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
)

// Mount registers the routes: pricing behind principal, the rest behind
// workspace, the edge's middleware for /v1/workspaces/{workspace}.
func Mount(r chi.Router, errs *httpx.Errors, principal, workspace func(http.Handler) http.Handler, s *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	r.With(principal).Get("/v1/pricing/currency", w.GetPricingCurrencyV1PricingCurrencyGet)

	base := r.With(workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	pc := httpx.WorkspacePrefix + "/provider-configs"
	mi := httpx.WorkspacePrefix + "/model-instances"
	cfg := []string{"config_id"}
	inst := []string{"instance_id"}

	on(request{query: configsQuery}).Get(pc+"/", w.ListProviderConfigsV1ProviderConfigsGet)
	on(request{body: createConfigBody}).Post(pc+"/", w.CreateProviderConfigV1ProviderConfigsPost)
	on(request{query: configsQuery}).Get(pc+"/with-instances", w.ListProviderConfigsWithInstancesV1ProviderConfigsWithInstancesGet)
	on(request{body: previewBody}).Post(pc+"/discover-preview", w.DiscoverModelsPreviewV1ProviderConfigsDiscoverPreviewPost)
	on(request{}).Get(pc+"/admin/{provider_key}/logo", w.GetProviderLogoV1ProviderConfigsAdminProviderKeyLogoGet)
	on(request{pathUUIDs: cfg}).Get(pc+"/{config_id}", w.GetProviderConfigV1ProviderConfigsConfigIdGet)
	on(request{pathUUIDs: cfg, body: updateConfigBody}).Put(pc+"/{config_id}", w.UpdateProviderConfigV1ProviderConfigsConfigIdPut)
	on(request{pathUUIDs: cfg, body: updateConfigBody}).Patch(pc+"/{config_id}", w.PatchProviderConfigV1ProviderConfigsConfigIdPatch)
	on(request{pathUUIDs: cfg}).Delete(pc+"/{config_id}", w.DeleteProviderConfigV1ProviderConfigsConfigIdDelete)
	on(request{pathUUIDs: cfg}).Post(pc+"/{config_id}/discover", w.DiscoverModelsV1ProviderConfigsConfigIdDiscoverPost)

	on(request{query: instancesQuery}).Get(mi+"/", w.ListModelInstancesV1ModelInstancesGet)
	on(request{body: instanceBody}).Post(mi+"/", w.CreateModelInstanceV1ModelInstancesPost)
	on(request{body: bulkBody}).Post(mi+"/bulk", w.CreateModelInstancesBulkV1ModelInstancesBulkPost)
	on(request{body: testBody}).Post(mi+"/test", w.ValidateModelInstanceV1ModelInstancesTestPost)
	on(request{pathUUIDs: inst}).Get(mi+"/{instance_id}", w.GetModelInstanceV1ModelInstancesInstanceIdGet)
	on(request{pathUUIDs: inst}).Delete(mi+"/{instance_id}", w.DeleteModelInstanceV1ModelInstancesInstanceIdDelete)
}
