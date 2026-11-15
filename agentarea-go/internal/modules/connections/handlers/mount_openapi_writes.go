package handlers

import (
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/service"
)

// mountOpenAPIWrites routes v1/openapi_connections.py's writes, the spec
// preview, the tool policies and discovery; from-catalog is mounted with
// the catalog item read.
func mountOpenAPIWrites(g group) {
	svc := g.s.svc
	if !svc.OpenAPIWritesReady() {
		return
	}
	p := httpx.WorkspacePrefix + "/openapi-connections"
	id := []string{"connection_id"}
	route := func(rq request, need string, method, path string, h func(http.ResponseWriter, *http.Request, *service.Service) error) {
		r := g.base
		if need != "" {
			r = r.With(requires(g.s, g.errs, need, "openapi_connection", "connection_id"))
		}
		r.With(rq.middleware(g.errs)).Method(method, path, g.errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
			return h(w, r, svc)
		}))
	}

	route(request{body: oaBody(func(v any, errs *[]httpx.FieldError) (struct{}, bool) {
		_, _, ok := previewBody(v, errs)
		return struct{}{}, ok
	})}, "", http.MethodPost, p+"/preview-spec", previewSpec)
	route(request{body: oaBody(connectionCreateBody)}, "", http.MethodPost, p+"/", createConnection)
	route(request{pathUUIDs: id, body: oaBody(connectionPatchBody)}, "edit", http.MethodPatch, p+"/{connection_id}", updateConnection)
	route(request{pathUUIDs: id, body: oaBody(oaSharingBody)}, "view", http.MethodPut, p+"/{connection_id}/sharing", setConnectionSharing)
	route(request{pathUUIDs: id}, "", http.MethodGet, p+"/{connection_id}/tool-policies", connectionToolPolicies)
	route(request{pathUUIDs: id}, "edit", http.MethodPost, p+"/{connection_id}/discover-tools", discoverConnectionTools)

	if svc.CatalogConnectReady() {
		item := []string{"catalog_item_id"}
		route(request{pathUUIDs: item}, "", http.MethodGet, p+"/from-catalog/{catalog_item_id}", catalogConnectForm)
		route(request{pathUUIDs: item, body: oaBody(catalogConnectBody)}, "", http.MethodPost, p+"/from-catalog/{catalog_item_id}", connectCatalogAPI)
	}
}
