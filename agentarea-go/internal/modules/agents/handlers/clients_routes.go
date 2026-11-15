package handlers

import (
	"errors"
	"net/http"
	"net/url"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	gen "github.com/agentarea/agentarea/agentarea-go/api/openapi/agents"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

type clientMiddleware = func(http.Handler) http.Handler

// clientRequires is route_authz.requires(permission, id_param=param): it runs
// before the route's parameters and body are validated, so a refusal (403)
// comes before a 422 about the body, and an unknown id is a 403 too.
func clientRequires(s *Server, errs *httpx.Errors, permission, param string) clientMiddleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw := chi.URLParam(r, param)
			id, err := uuid.Parse(raw)
			if err != nil {
				errs.Write(w, r, httpx.Validation(httpx.FieldError{Type: "uuid_parsing", Loc: []any{"path", param}, Msg: "Input should be a valid UUID"}))
				return
			}
			c, err := caller(r.Context())
			if err == nil {
				err = s.svc.Require(r.Context(), c, permission, id)
			}
			if err != nil {
				errs.Write(w, r, err)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// clientScope is route_authz.requires_scope.
func clientScope(errs *httpx.Errors, sc authn.Scope, action string) clientMiddleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c, err := caller(r.Context())
			if err == nil {
				err = authn.EnsureScope(c.Principal, sc, action)
			}
			if err != nil {
				errs.Write(w, r, err)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// clientDropQuery hides the query the parse functions already validated from
// the generated wrapper, whose parsing is not pydantic's.
func clientDropQuery(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		r.URL.RawQuery = ""
		next.ServeHTTP(w, r)
	})
}

// clientChain is the workspace admission, then mws, then rq's validation.
func clientChain(r chi.Router, e Edge, errs *httpx.Errors, rq request, mws ...clientMiddleware) chi.Router {
	all := append([]clientMiddleware{e.Workspace}, mws...)
	return r.With(append(all, rq.middleware(errs), clientDropQuery)...)
}

// mountClients registers the Clients routes.
func mountClients(r chi.Router, _ func(rq request) chi.Router, w *gen.ServerInterfaceWrapper, e Edge, s *Server, errs *httpx.Errors) {
	p := httpx.WorkspacePrefix + "/clients"
	id := []string{"client_id"}
	edit := func(rq request) chi.Router {
		return clientChain(r, e, errs, rq, clientRequires(s, errs, "edit", "client_id"))
	}

	clientChain(r, e, errs, request{query: clientListQuery}).Get(p+"/", w.ListClientsV1ClientsGet)
	clientChain(r, e, errs, request{body: clientCreateBody}).Post(p+"/", w.CreateClientV1ClientsPost)
	clientChain(r, e, errs, request{}).Get(p+"/platform-toolsets", w.ListPlatformToolsetsV1ClientsPlatformToolsetsGet)
	clientChain(r, e, errs, request{pathUUIDs: id}, clientRequires(s, errs, "read", "client_id")).
		Get(p+"/{client_id}", w.GetClientV1ClientsClientIdGet)
	edit(request{pathUUIDs: id, body: clientUpdateBody}).Patch(p+"/{client_id}", w.UpdateClientV1ClientsClientIdPatch)
	clientChain(r, e, errs, request{pathUUIDs: id}, clientRequires(s, errs, "delete", "client_id")).
		Delete(p+"/{client_id}", w.DeleteClientV1ClientsClientIdDelete)

	edit(request{pathUUIDs: id, body: clientAssociationBody(false)}).Post(p+"/{client_id}/skills", w.AddSkillToClientV1ClientsClientIdSkillsPost)
	edit(request{pathUUIDs: []string{"client_id", "skill_id"}}).
		Delete(p+"/{client_id}/skills/{skill_id}", w.RemoveSkillFromClientV1ClientsClientIdSkillsSkillIdDelete)
	edit(request{pathUUIDs: id, body: clientAssociationBody(true)}).
		Post(p+"/{client_id}/mcp-instances", w.AddMcpInstanceToClientV1ClientsClientIdMcpInstancesPost)
	edit(request{pathUUIDs: []string{"client_id", "mcp_instance_id"}}).
		Delete(p+"/{client_id}/mcp-instances/{mcp_instance_id}", w.RemoveMcpInstanceFromClientV1ClientsClientIdMcpInstancesMcpInstanceIdDelete)
	edit(request{pathUUIDs: id, body: clientAssociationBody(true)}).
		Post(p+"/{client_id}/openapi-connections", w.AddOpenapiConnectionToClientV1ClientsClientIdOpenapiConnectionsPost)
	edit(request{pathUUIDs: []string{"client_id", "connection_id"}}).
		Delete(p+"/{client_id}/openapi-connections/{connection_id}", w.RemoveOpenapiConnectionFromClientV1ClientsClientIdOpenapiConnectionsConnectionIdDelete)
	edit(request{pathUUIDs: id, body: clientToolsetBody}).
		Post(p+"/{client_id}/platform-toolsets", w.AddPlatformToolsetToClientV1ClientsClientIdPlatformToolsetsPost)
	edit(request{pathUUIDs: id}).Delete(p+"/{client_id}/platform-toolsets/*", clientRemoveToolset(s, errs))

	clientChain(r, e, errs, request{pathUUIDs: id}, clientRequires(s, errs, "use", "client_id")).
		Post(p+"/{client_id}/agent", w.HarnessAgentV1ClientsClientIdAgentPost)
	clientChain(r, e, errs, request{pathUUIDs: id}, clientScope(errs, authn.ScopeCredentials, "issue runner keys"),
		clientRequires(s, errs, "edit", "client_id")).Post(p+"/{client_id}/runner-keys", w.IssueRunnerKeyV1ClientsClientIdRunnerKeysPost)
	edit(request{pathUUIDs: id}).Get(p+"/{client_id}/runner-keys", w.ListRunnerKeysV1ClientsClientIdRunnerKeysGet)
	clientChain(r, e, errs, request{pathUUIDs: []string{"client_id", "key_id"}}, clientScope(errs, authn.ScopeCredentials, "revoke runner keys"),
		clientRequires(s, errs, "edit", "client_id")).Delete(p+"/{client_id}/runner-keys/{key_id}", w.RevokeRunnerKeyV1ClientsClientIdRunnerKeysKeyIdDelete)
}

// clientRemoveToolset serves DELETE .../platform-toolsets/{toolset:path}: the
// toolset is the rest of the path, slashes included, percent-decoded.
func clientRemoveToolset(s *Server, errs *httpx.Errors) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		toolset := chi.URLParam(r, "*")
		if r.URL.RawPath != "" {
			if v, err := url.PathUnescape(toolset); err == nil {
				toolset = v
			}
		}
		res, err := s.RemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDelete(r.Context(),
			gen.RemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDeleteRequestObject{
				Workspace: chi.URLParam(r, httpx.WorkspaceParam), ClientId: uuid.MustParse(chi.URLParam(r, "client_id")), Toolset: toolset,
			})
		if err == nil {
			err = res.VisitRemovePlatformToolsetFromClientV1ClientsClientIdPlatformToolsetsToolsetDeleteResponse(w)
		}
		if err != nil {
			errs.Write(w, r, err)
		}
	}
}

func mapClientError(err error) (*httpx.Error, bool) {
	var (
		inUse   *service.ClientInUseError
		toolset *domain.ClientToolsetError
	)
	switch {
	case errors.Is(err, service.ErrClientNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Client not found"), true
	case errors.Is(err, service.ErrClientRunnerKeyNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Runner key not found"), true
	case errors.Is(err, service.ErrClientNoRunner):
		return httpx.HTTPError(http.StatusUnprocessableEntity, err.Error()), true
	case errors.As(err, &inUse):
		return httpx.Conflict(inUse.Error()), true
	case errors.As(err, &toolset):
		return httpx.HTTPError(http.StatusUnprocessableEntity, toolset.Msg), true
	}
	return nil, false
}
