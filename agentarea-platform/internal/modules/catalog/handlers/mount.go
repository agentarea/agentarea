package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/catalog"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
)

// platformWrite is require_platform_catalog_write: a route dependency, so
// it refuses before the parameters are validated.
func (s *Server) platformWrite(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c, err := caller(r.Context())
			if err == nil {
				err = s.svc.RequirePlatformWrite(r.Context(), c)
			}
			if err != nil {
				errs.Write(w, r, err)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// adminOnly is requires_workspace_admin, a route dependency like platformWrite.
func (s *Server) adminOnly(errs *httpx.Errors) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if err := s.admin(r.Context()); err != nil {
				errs.Write(w, r, err)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// Mount registers the catalog routes on r behind workspace. Browse and the
// item card are mounted only with the connections and pricing ports.
func Mount(r chi.Router, errs *httpx.Errors, workspace func(http.Handler) http.Handler, s *Server) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	s.errs = errs
	base := r.With(workspace)
	on := func(rq request) chi.Router { return base.With(rq.middleware(errs)) }
	write := func(rq request) chi.Router { return base.With(s.platformWrite(errs), rq.middleware(errs)) }
	admin := func(rq request) chi.Router { return base.With(s.adminOnly(errs), rq.middleware(errs)) }
	p := httpx.WorkspacePrefix + "/registries"
	reg := []string{"registry_id"}
	item := []string{"item_id"}

	write(request{body: registryCreateBody}).Post(p+"/", w.CreateRegistryV1RegistriesPost)
	on(request{query: listRegistriesQuery}).Get(p+"/", w.ListRegistriesV1RegistriesGet)
	on(request{query: searchQuery}).Get(p+"/catalog/search", w.SearchCatalogV1RegistriesCatalogSearchGet)
	on(request{pathUUIDs: reg}).Get(p+"/{registry_id}", w.GetRegistryV1RegistriesRegistryIdGet)
	write(request{pathUUIDs: reg, body: registryUpdateBody}).Patch(p+"/{registry_id}", w.UpdateRegistryV1RegistriesRegistryIdPatch)
	write(request{pathUUIDs: reg}).Delete(p+"/{registry_id}", w.DeleteRegistryV1RegistriesRegistryIdDelete)
	on(request{pathUUIDs: reg, query: pageQuery}).Get(p+"/{registry_id}/items", w.ListRegistryItemsV1RegistriesRegistryIdItemsGet)
	write(request{pathUUIDs: reg, body: itemCreateBody}).Post(p+"/{registry_id}/items", w.CreateCatalogItemV1RegistriesRegistryIdItemsPost)
	write(request{pathUUIDs: item, body: itemUpdateBody}).Patch(p+"/catalog/items/{item_id}", w.UpdateCatalogItemV1RegistriesCatalogItemsItemIdPatch)
	write(request{pathUUIDs: item}).Delete(p+"/catalog/items/{item_id}", w.DeleteCatalogItemV1RegistriesCatalogItemsItemIdDelete)
	write(request{pathUUIDs: item}).Post(p+"/catalog/items/{item_id}/update", w.UpdateItemSpecV1RegistriesCatalogItemsItemIdUpdatePost)
	write(request{pathUUIDs: reg}).Post(p+"/{registry_id}/update-all", w.UpdateAllSpecsV1RegistriesRegistryIdUpdateAllPost)
	if s.svc.HasSync() {
		write(request{pathUUIDs: reg}).Post(p+"/{registry_id}/sync", w.SyncRegistryV1RegistriesRegistryIdSyncPost)
	}
	if s.connections != nil && s.pricing != nil {
		on(request{query: browseQuery}).Get(p+"/catalog/browse", w.BrowseCatalogV1RegistriesCatalogBrowseGet)
		on(request{pathUUIDs: item}).Get(p+"/catalog/items/{item_id}", w.GetCatalogItemV1RegistriesCatalogItemsItemIdGet)
	}

	wr := httpx.WorkspacePrefix + "/workspace-registries"
	on(request{}).Get(wr, w.ListWorkspaceRegistriesV1WorkspaceRegistriesGet)
	on(request{pathUUIDs: reg}).Get(wr+"/{registry_id}", w.GetWorkspaceRegistryV1WorkspaceRegistriesRegistryIdGet)
	if s.admin != nil && s.svc.HasSecrets() {
		admin(request{body: wsRegistryCreateBody}).Post(wr, w.CreateWorkspaceRegistryV1WorkspaceRegistriesPost)
		admin(request{pathUUIDs: reg, body: wsRegistryUpdateBody}).Patch(wr+"/{registry_id}", w.UpdateWorkspaceRegistryV1WorkspaceRegistriesRegistryIdPatch)
		if s.svc.HasSync() {
			admin(request{pathUUIDs: reg}).Delete(wr+"/{registry_id}", w.DeleteWorkspaceRegistryV1WorkspaceRegistriesRegistryIdDelete)
		}
	}
	if s.admin != nil && s.rate != nil && s.svc.HasSync() {
		admin(request{pathUUIDs: reg, query: forceQuery}).Post(wr+"/{registry_id}/sync", w.SyncWorkspaceRegistryV1WorkspaceRegistriesRegistryIdSyncPost)
	}

	if s.bundles != nil {
		on(request{body: analyzeBody}).Post(httpx.WorkspacePrefix+"/bundles/analyze", w.AnalyzeBundleV1BundlesAnalyzePost)
		on(request{body: installBody}).Post(httpx.WorkspacePrefix+"/bundles/install", w.InstallBundleV1BundlesInstallPost)
	}

	ps := httpx.WorkspacePrefix + "/provider-specs"
	provider := []string{"provider_spec_id"}
	if s.svc.HasSpecUse() {
		on(request{query: providerSpecsQuery}).Get(ps+"/", w.ListProviderSpecsV1ProviderSpecsGet)
		on(request{query: providerSpecsQuery}).Get(ps+"/with-models", w.ListProviderSpecsWithModelsV1ProviderSpecsWithModelsGet)
	}
	on(request{pathUUIDs: provider}).Get(ps+"/{provider_spec_id}", w.GetProviderSpecV1ProviderSpecsProviderSpecIdGet)
	on(request{}).Get(ps+"/by-key/{provider_key}", w.GetProviderSpecByKeyV1ProviderSpecsByKeyProviderKeyGet)

	ms := httpx.WorkspacePrefix + "/model-specs"
	spec := []string{"model_spec_id"}
	on(request{query: modelSpecsQuery}).Get(ms+"/", w.ListModelSpecsV1ModelSpecsGet)
	on(request{pathUUIDs: spec}).Get(ms+"/{model_spec_id}", w.GetModelSpecV1ModelSpecsModelSpecIdGet)
	on(request{pathUUIDs: provider, query: byProviderQuery}).Get(ms+"/by-provider/{provider_spec_id}", w.ListModelSpecsByProviderV1ModelSpecsByProviderProviderSpecIdGet)
	on(request{pathUUIDs: provider}).Get(ms+"/by-provider/{provider_spec_id}/{model_name}", w.GetModelSpecByProviderAndNameV1ModelSpecsByProviderProviderSpecIdModelNameGet)
	if s.admin != nil {
		admin(request{body: modelCreateBody}).Post(ms+"/", w.CreateModelSpecV1ModelSpecsPost)
		admin(request{pathUUIDs: spec, body: modelUpdateBody}).Patch(ms+"/{model_spec_id}", w.UpdateModelSpecV1ModelSpecsModelSpecIdPatch)
		admin(request{pathUUIDs: spec}).Delete(ms+"/{model_spec_id}", w.DeleteModelSpecV1ModelSpecsModelSpecIdDelete)
		admin(request{body: modelCreateBody}).Post(ms+"/upsert", w.UpsertModelSpecV1ModelSpecsUpsertPost)
	}
}
