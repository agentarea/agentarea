package handlers

import (
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/service"
)

// oauthHopHeaders are not copied from Hydra's answer: the proxy frames its own response.
// registerMaxBody caps the anonymous client registration document, far
// under AGENTAREA_API_MAX_BODY.
const registerMaxBody = 64 << 10

func oauthHopHeaders() []string {
	return []string{"Connection", "Keep-Alive", "Transfer-Encoding", "Content-Length", "Upgrade", "Proxy-Connection", "Te", "Trailer"}
}

// mountOAuthAS is v1/mcp_oauth_as.py: RFC 9728 metadata and the proxy to
// Hydra that makes this API usable as an MCP client's authorization server.
// Root routes, unauthenticated by protocol.
func mountOAuthAS(g group) {
	svc := g.s.svc
	if !svc.OAuthASReady() {
		return
	}
	h := g.errs.Handler
	g.r.Method(http.MethodGet, "/.well-known/oauth-protected-resource", h(func(w http.ResponseWriter, r *http.Request) error {
		return writeProtectedResource(w, r, svc, "mcp")
	}))
	g.r.Method(http.MethodGet, "/.well-known/oauth-protected-resource/*", h(func(w http.ResponseWriter, r *http.Request) error {
		path := chi.URLParam(r, "*")
		if !service.IsProtectedResource(path) {
			return httpx.HTTPError(http.StatusNotFound, "Unknown protected resource")
		}
		return writeProtectedResource(w, r, svc, path)
	}))
	g.r.Method(http.MethodGet, "/.well-known/oauth-authorization-server", h(func(w http.ResponseWriter, r *http.Request) error {
		doc, err := svc.AuthorizationServerMetadata(r.Context())
		if err != nil {
			return httpx.HTTPError(http.StatusBadGateway, "Authorization server unavailable").Wrap(err)
		}
		return writeOAuthJSON(w, http.StatusOK, doc)
	}))
	g.r.Method(http.MethodGet, "/.well-known/jwks.json", h(func(w http.ResponseWriter, r *http.Request) error {
		return oauthProxyHydra(w, r, svc, "/.well-known/jwks.json", 10*time.Second)
	}))
	g.r.Method(http.MethodGet, "/oauth2/auth", h(func(w http.ResponseWriter, r *http.Request) error {
		http.Redirect(w, r, svc.HydraAuthorizeURL(r.URL.RawQuery), http.StatusFound)
		return nil
	}))
	g.r.Method(http.MethodPost, "/oauth2/register", h(func(w http.ResponseWriter, r *http.Request) error {
		if err := httpx.EnforceRateLimit(r.Context(), g.s.rate, g.s.log, httpx.OAuthRegisterScope, httpx.ClientIdentity(r), httpx.OAuthRegisterLimit); err != nil {
			return err
		}
		body, err := io.ReadAll(io.LimitReader(r.Body, registerMaxBody+1))
		if err != nil {
			return err
		}
		if len(body) > registerMaxBody {
			return httpx.ErrBodyTooLarge
		}
		reg, err := svc.Registration(body)
		var refusal *service.DCRRefusal
		if errors.As(err, &refusal) {
			return writeOAuthJSON(w, http.StatusBadRequest, wirejson.Object{
				{Key: "error", Value: refusal.Code}, {Key: "error_description", Value: refusal.Description},
			})
		}
		if err != nil {
			return err
		}
		status, out, err := svc.RegisterClient(r.Context(), reg)
		if err != nil {
			return httpx.HTTPError(http.StatusBadGateway, "Authorization server unavailable").Wrap(err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Content-Length", strconv.Itoa(len(out)))
		w.WriteHeader(status)
		_, err = w.Write(out)
		return err
	}))
	proxy := h(func(w http.ResponseWriter, r *http.Request) error {
		path := chi.URLParam(r, "*")
		if !service.SafeOAuth2Path(path) {
			return writeOAuthJSON(w, http.StatusBadRequest, wirejson.Object{
				{Key: "error", Value: "invalid_request"}, {Key: "error_description", Value: "invalid oauth2 path"},
			})
		}
		return oauthProxyHydra(w, r, svc, "/oauth2/"+path, 30*time.Second)
	})
	for _, m := range []string{http.MethodGet, http.MethodPost, http.MethodPut, http.MethodDelete, http.MethodPatch} {
		g.r.Method(m, "/oauth2/*", proxy)
	}
}

func writeProtectedResource(w http.ResponseWriter, r *http.Request, svc *service.Service, path string) error {
	doc, err := svc.ProtectedResource(r.Context(), path)
	if err != nil {
		return httpx.HTTPError(http.StatusBadGateway, "Authorization server unavailable").Wrap(err)
	}
	return writeOAuthJSON(w, http.StatusOK, doc)
}

func oauthProxyHydra(w http.ResponseWriter, r *http.Request, svc *service.Service, path string, timeout time.Duration) error {
	resp, err := svc.HydraProxy(r.Context(), r.Method, path, r.URL.RawQuery, r.Header, r.Body, timeout)
	if err != nil {
		return httpx.HTTPError(http.StatusBadGateway, "Authorization server unavailable").Wrap(err)
	}
	defer func() { _ = resp.Body.Close() }()
	for k, vs := range resp.Header {
		skip := false
		for _, hop := range oauthHopHeaders() {
			skip = skip || strings.EqualFold(k, hop)
		}
		if !skip {
			w.Header()[k] = vs
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, err = io.Copy(w, resp.Body)
	return err
}
