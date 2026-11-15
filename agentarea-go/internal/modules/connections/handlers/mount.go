package handlers

import (
	"context"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/connections"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/mcpserve"
)

// Edge is what the routes need from the serve edge.
type Edge struct {
	// Workspace admits the caller into /v1/workspaces/{workspace}.
	Workspace func(http.Handler) http.Handler
	// Admin refuses a caller of the workspace in ctx who is not its admin
	// (requires_workspace_admin).
	Admin func(ctx context.Context) error
	// Gate resolves bearer tokens and workspace entry on the MCP surfaces;
	// Authenticate is get_principal (no workspace in the path). Nil leaves
	// those routes unmounted.
	Gate         authn.Gate
	Authenticate func(http.Handler) http.Handler
}

// Ports says which route groups have their ports: the OpenAPI connections
// need the graph and the secret store, and are not routed without them.
type Ports struct {
	OpenAPI bool
	// MCPToolsets are the platform toolsets /mcp and /mcp/w/{workspace} serve.
	MCPToolsets []mcpserve.Toolset
}

// Mount registers the ported routes. The admin groups are the auth configs and
// the OAuth links; the OpenAPI group is the list, get and delete. The ported
// routes sit under /v1/workspaces/{workspace}.
func Mount(r chi.Router, errs *httpx.Errors, e Edge, s *Server, ports Ports) {
	w := &gen.ServerInterfaceWrapper{
		Handler: gen.NewStrictHandlerWithOptions(s, nil, gen.StrictHTTPServerOptions{
			RequestErrorHandlerFunc: errs.Write, ResponseErrorHandlerFunc: errs.Write,
		}),
		ErrorHandlerFunc: errs.Write,
	}
	base := r.With(e.Workspace)
	admin := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(rw http.ResponseWriter, rq *http.Request) {
			if err := e.Admin(rq.Context()); err != nil {
				errs.Write(rw, rq, err)
				return
			}
			next.ServeHTTP(rw, rq)
		})
	}
	adminOn := func(rq request) chi.Router { return base.With(admin, rq.middleware(errs)) }
	p := httpx.WorkspacePrefix

	adminOn(request{}).Get(p+"/mcp-auth-configs/", w.ListMcpAuthConfigsV1McpAuthConfigsGet)
	adminOn(request{body: authCreateBody}).Post(p+"/mcp-auth-configs/", w.CreateMcpAuthConfigV1McpAuthConfigsPost)
	adminOn(request{pathUUIDs: []string{"config_id"}}).Get(p+"/mcp-auth-configs/{config_id}", w.GetMcpAuthConfigV1McpAuthConfigsConfigIdGet)
	adminOn(request{pathUUIDs: []string{"config_id"}, body: authUpdateBody}).Put(p+"/mcp-auth-configs/{config_id}", w.UpdateMcpAuthConfigV1McpAuthConfigsConfigIdPut)
	adminOn(request{pathUUIDs: []string{"config_id"}}).Delete(p+"/mcp-auth-configs/{config_id}", w.DeleteMcpAuthConfigV1McpAuthConfigsConfigIdDelete)

	adminOn(request{body: linkBody}).Post(p+"/mcp-oauth-links/", w.CreateOauthLinkV1McpOauthLinksPost)
	adminOn(request{pathUUIDs: []string{"instance_id"}}).Get(p+"/mcp-oauth-links/instance/{instance_id}", w.ListOauthLinksForInstanceV1McpOauthLinksInstanceInstanceIdGet)
	adminOn(request{pathUUIDs: []string{"link_id"}}).Get(p+"/mcp-oauth-links/{link_id}", w.GetOauthLinkV1McpOauthLinksLinkIdGet)
	adminOn(request{pathUUIDs: []string{"link_id"}}).Delete(p+"/mcp-oauth-links/{link_id}", w.RevokeOauthLinkV1McpOauthLinksLinkIdDelete)

	g := group{r: r, errs: errs, e: e, s: s, w: w, base: base, adminOn: adminOn, ports: ports}
	mountInstances(g)
	mountVerify(g)
	mountOAuthConnect(g)
	mountOAuthAS(g)
	mountProxy(g)
	mountMCP(g)
	if !ports.OpenAPI {
		return
	}
	mountOpenAPIWrites(g)
	on := func(rq request, mws ...func(http.Handler) http.Handler) chi.Router {
		return base.With(append(mws, rq.middleware(errs))...)
	}
	id := []string{"connection_id"}
	on(request{query: listQuery}).Get(p+"/openapi-connections/", w.ListConnectionsV1OpenapiConnectionsGet)
	on(request{pathUUIDs: id}).Get(p+"/openapi-connections/{connection_id}", w.GetConnectionV1OpenapiConnectionsConnectionIdGet)
	on(request{pathUUIDs: id}, requires(s, errs, "delete", "openapi_connection", "connection_id")).
		Delete(p+"/openapi-connections/{connection_id}", w.DeleteConnectionV1OpenapiConnectionsConnectionIdDelete)
}

// requires is route_authz.requires(permission, id_param=param): it runs before
// the route's parameters and body are validated, so a refusal (403) comes first.
func requires(s *Server, errs *httpx.Errors, permission, resourceType, param string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw, fe := httpx.ValidateUUID(chi.URLParam(r, param), "path", param)
			if fe != nil {
				errs.Write(w, r, httpx.Validation(*fe))
				return
			}
			c, err := caller(r.Context())
			if err == nil {
				err = s.svc.Require(r.Context(), c, permission, resourceType, uuid.MustParse(raw).String())
			}
			if err != nil {
				errs.Write(w, r, err)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
