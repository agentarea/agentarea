package mcpserver

import (
	"bytes"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"regexp"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

var workspaceReference = regexp.MustCompile(`^(?:[a-z0-9-]{1,120}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$`)

// ValidWorkspaceReference is WORKSPACE_REFERENCE_PATTERN: a slug or a workspace id.
func ValidWorkspaceReference(ref string) bool { return workspaceReference.MatchString(ref) }

// IsHandshake is a method served without a token: initialize, ping and notifications.
func IsHandshake(method string) bool {
	return method == "initialize" || method == "ping" || strings.HasPrefix(method, "notifications/")
}

// Auth is MCPAuthMiddleware: every protected request carries its own bearer
// token; nothing is kept between requests.
type Auth struct {
	Gate   authn.Gate
	APIURL string
	// AdmitTurn lets a runner turn's token in (the client endpoint only).
	AdmitTurn bool
	Log       *slog.Logger
}

// Mount describes one request's resource for the auth decision.
type Mount struct {
	// Resource is the RFC 9728 resource path the 401 names ("" for /mcp).
	Resource string
	// Workspace is the reference a pinned URL names ("" when none).
	Workspace string
}

// Wrap authenticates the request at mount m and puts the principal (and, on a
// pinned mount, the caller in that workspace) into its context.
func (a Auth) Wrap(next http.Handler, mount func(r *http.Request) Mount) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(io.LimitReader(r.Body, maxBody+1))
		if err != nil {
			WriteError(w, http.StatusBadRequest, nil, &Error{Code: CodeParseError, Message: "Parse error"})
			return
		}
		r.Body = io.NopCloser(bytes.NewReader(body))
		method, id := PeekMethod(body)
		m := mount(r)
		ctx := r.Context()
		authenticated, denied := false, false
		if token, ok := bearer(r.Header.Get("Authorization")); ok {
			c, p, refusedWorkspace := a.authenticate(r, token, m.Workspace)
			switch {
			case refusedWorkspace:
				denied = true
			case p != nil:
				authenticated = true
				ctx = authn.WithPrincipal(ctx, *p)
				if c != nil {
					ctx = authn.WithCaller(ctx, *c)
				}
			}
		}
		if !authenticated && !IsHandshake(method) {
			if denied {
				WriteError(w, http.StatusForbidden, id, &Error{Code: CodeInvalidRequest, Message: "No accessible workspace '" + m.Workspace + "'"})
				return
			}
			a.log().Info("MCP auth: rejecting unauthenticated request", "method", method)
			w.Header().Set("WWW-Authenticate", a.challenge(m.Resource))
			WriteError(w, http.StatusUnauthorized, id, &Error{Code: CodeInvalidRequest, Message: "Authentication required. Provide a valid Bearer token."})
			return
		}
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (a Auth) log() *slog.Logger {
	if a.Log == nil {
		return slog.New(slog.DiscardHandler)
	}
	return a.Log
}

func bearer(header string) (string, bool) {
	const pre = "bearer "
	if len(header) < len(pre) || !strings.EqualFold(header[:len(pre)], pre) {
		return "", false
	}
	return header[len(pre):], true
}

func (a Auth) challenge(resource string) string {
	location := strings.TrimRight(a.APIURL, "/") + "/.well-known/oauth-protected-resource"
	if r := strings.Trim(resource, "/"); r != "" {
		location += "/" + r
	}
	return `Bearer resource_metadata="` + location + `"`
}

// authenticate is _try_authenticate: it never fails the request; a token
// that resolves to nobody reads as no token, and refusedWorkspace marks a
// valid token whose pinned workspace is out of reach.
func (a Auth) authenticate(r *http.Request, token, pinned string) (c *authn.Caller, p *authn.Principal, refusedWorkspace bool) {
	ctx := r.Context()
	p, err := a.Gate.Optional(ctx, token, authn.SurfaceMCP, a.AdmitTurn)
	if err != nil {
		a.log().Warn("MCP auth: token validation error", "error", err)
		return nil, nil, false
	}
	if p == nil {
		return nil, nil, false
	}
	if p.BoundAgentID != "" {
		a.log().Info("MCP auth: refused a key bound to an agent", "agent_id", p.BoundAgentID)
		return nil, nil, false
	}
	if p.Credential != nil {
		cred := *p.Credential
		cred.Surface = authn.SurfaceMCP
		p.Credential = &cred
	}
	if pinned == "" {
		return nil, p, false
	}
	caller, err := a.Gate.EnterWorkspace(ctx, *p, pinned)
	if err != nil {
		var unreachable *scope.UnreachableError
		if errors.As(err, &unreachable) {
			a.log().Warn("MCP auth: rejected pinned workspace", "user_id", p.UserID, "requested", pinned, "accessible", p.AccessibleWorkspaces)
			return nil, nil, true
		}
		a.log().Warn("MCP auth: token validation error", "error", err)
		return nil, nil, false
	}
	return &caller, p, false
}
