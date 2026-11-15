package app

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// edge admits callers at the HTTP edge (auth/dependencies.py): every core
// module and every extension route gets its middleware from here.
type edge struct {
	gate   authn.Gate
	admins authz.Admins
	// errs renders a refusal; the edge module sets it when it mounts, before
	// any request runs.
	errs *httpx.Errors
}

// newEdge builds the edge over the gate and the admin authority.
func newEdge(gate authn.Gate, admins authz.Admins) *edge {
	return &edge{gate: gate, admins: admins}
}

// Workspace is get_user_context on /v1/workspaces/{workspace}: the
// principal, then its admission into the workspace the path names, both
// put into the request context.
func (e *edge) Workspace(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		p, err := e.gate.Authenticate(ctx, r)
		if err != nil {
			e.errs.Write(w, r, err)
			return
		}
		ref := chi.URLParam(r, httpx.WorkspaceParam)
		c, err := e.gate.Caller(ctx, p, authn.Route{WorkspaceRef: ref, HasWorkspaceRef: true})
		if err != nil {
			e.errs.Write(w, r, err)
			return
		}
		ctx = authn.WithCaller(authn.WithPrincipal(ctx, c.Principal), c)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// Principal is get_principal: a route that acts on no single workspace.
func (e *edge) Principal(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := r.Context()
		p, err := e.gate.Authenticate(ctx, r)
		if err == nil {
			p, err = e.gate.Principal(ctx, p)
		}
		if err != nil {
			e.errs.Write(w, r, err)
			return
		}
		next.ServeHTTP(w, r.WithContext(authn.WithPrincipal(ctx, p)))
	})
}

// RequireAdmin is requires_workspace_admin for c.
func (e *edge) RequireAdmin(ctx context.Context, c authn.Caller) error {
	return e.admins.Require(ctx, &c)
}

// Admin is RequireAdmin for the caller Workspace put into ctx.
func (e *edge) Admin(ctx context.Context) error {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.ErrWorkspaceNotSelected
	}
	return e.RequireAdmin(ctx, c)
}

// extension is the edge as extension routes take it.
func (e *edge) extension() extensionEdge {
	return extensionEdge{Workspace: e.Workspace, Authenticate: e.Principal, RequireAdmin: e.RequireAdmin}
}

// module is mounted first: it renders the edge's refusals as Python raises
// them and hands the edge the renderer.
func (e *edge) module() serve.Module {
	return serve.Module{
		Name:   "edge",
		Errors: edgeErrors,
		Mount: func(rt serve.Routes) error {
			e.errs = rt.Errors
			return nil
		},
	}
}

// edgeErrors maps the kernel's admission errors: an HTTPException with its
// challenge, ScopeRequiredError (a PermissionError), and the admin checks.
func edgeErrors(err error) (*httpx.Error, bool) {
	var refused *authn.Error
	var scopeErr *authn.ScopeRequiredError
	switch {
	case errors.As(err, &refused):
		out := httpx.HTTPError(refused.Status, refused.Detail).Wrap(err)
		if refused.WWWAuthenticate != "" {
			out = out.WithHeader("WWW-Authenticate", refused.WWWAuthenticate)
		}
		return out, true
	case errors.As(err, &scopeErr):
		return httpx.Forbidden(scopeErr.Error()).Wrap(err), true
	case errors.Is(err, authz.ErrNotWorkspaceAdmin):
		return httpx.HTTPError(http.StatusForbidden, authz.NotAdminDetail).Wrap(err), true
	case errors.Is(err, authz.ErrWorkspaceRequired):
		return httpx.HTTPError(http.StatusUnprocessableEntity, authz.WorkspaceRequiredDetail).Wrap(err), true
	}
	return nil, false
}

// slashRedirect is mounted last: Starlette's redirect_slashes. A path no
// route matches, whose twin with the trailing slash toggled does match some
// route, answers 307 to the twin; anything else is the mux's 404.
func slashRedirect() serve.Module {
	return serve.Module{
		Name: "redirect slashes",
		Mount: func(rt serve.Routes) error {
			mux, ok := rt.Mux.Chi().(*chi.Mux)
			if !ok {
				return errors.New("the router is not a chi mux")
			}
			notFound := mux.NotFoundHandler()
			mux.NotFound(func(w http.ResponseWriter, r *http.Request) {
				if target, ok := toggledMatch(mux, r); ok {
					scheme := "http"
					if r.TLS != nil {
						scheme = "https"
					}
					loc := scheme + "://" + r.Host + target
					if r.URL.RawQuery != "" {
						loc += "?" + r.URL.RawQuery
					}
					w.Header().Set("Location", loc)
					w.Header().Set("Content-Length", "0")
					w.WriteHeader(http.StatusTemporaryRedirect)
					return
				}
				notFound.ServeHTTP(w, r)
			})
			return nil
		},
	}
}

func slashMethods() []string {
	return []string{
		http.MethodGet, http.MethodHead, http.MethodPost, http.MethodPut,
		http.MethodPatch, http.MethodDelete, http.MethodOptions,
	}
}

func toggledMatch(mux *chi.Mux, r *http.Request) (string, bool) {
	path := r.URL.EscapedPath()
	if path == "/" || path == "" {
		return "", false
	}
	twin := path + "/"
	if strings.HasSuffix(path, "/") {
		twin = strings.TrimRight(path, "/")
		if twin == "" {
			return "", false
		}
	}
	for _, m := range slashMethods() {
		if mux.Match(chi.NewRouteContext(), m, twin) {
			return twin, true
		}
	}
	return "", false
}
