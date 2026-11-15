package handlers

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/service"
)

// Edge is what the HTTP edge resolves before a handler runs.
type Edge struct {
	// Workspace admits the caller into /v1/workspaces/{workspace}.
	Workspace func(http.Handler) http.Handler
	// Principal authenticates a route that acts on no single workspace.
	Principal func(http.Handler) http.Handler
	// Admin refuses a caller that does not administer its workspace
	// (requires_workspace_admin).
	Admin func(ctx context.Context) error
}

// Server serves the ported identity routes.
type Server struct {
	svc  *service.Service
	edge Edge
	errs *httpx.Errors
}

// MapError renders the module's errors as Python raises them.
func MapError(err error) (*httpx.Error, bool) {
	var inv *domain.InvitationError
	var refusal *domain.Refusal
	var own *domain.OwnershipUnavailableError
	switch {
	case errors.As(err, &inv):
		return httpx.HTTPError(inv.Status, inv.Detail), true
	case errors.As(err, &refusal):
		return httpx.HTTPError(refusal.Status, refusal.Detail), true
	case errors.As(err, &own):
		return httpx.NewError(http.StatusServiceUnavailable, "resource_ownership_unavailable", own.Error()), true
	case errors.Is(err, domain.ErrAgentNotFound):
		return httpx.HTTPError(http.StatusNotFound, "Agent not found"), true
	case errors.Is(err, domain.ErrAPIKeyCreateFailed):
		return httpx.HTTPError(http.StatusInternalServerError, "Failed to create API key"), true
	case errors.Is(err, domain.ErrGraphSeedFailed):
		return httpx.HTTPError(http.StatusServiceUnavailable, "Workspace authorization graph unavailable"), true
	case errors.Is(err, domain.ErrMembershipGraphDown):
		return httpx.HTTPError(http.StatusServiceUnavailable, "Workspace membership graph unavailable"), true
	case errors.Is(err, domain.ErrEmptyWorkspaceName):
		return httpx.HTTPError(http.StatusUnprocessableEntity, "Workspace name must not be empty"), true
	}
	return nil, false
}

// Mount registers POST /v1/workspaces, POST /v1/invitations/accept, and
// under a workspace POST /invitations and POST /api-keys/.
func Mount(r chi.Router, errs *httpx.Errors, edge Edge, svc *service.Service) {
	s := &Server{svc: svc, edge: edge, errs: errs}
	r.With(edge.Principal).Post("/v1/workspaces", errs.Handler(s.createWorkspace).ServeHTTP)
	r.With(edge.Principal).Post("/v1/invitations/accept", errs.Handler(s.acceptInvitation).ServeHTTP)
	r.With(edge.Workspace).Post(httpx.WorkspacePrefix+"/invitations", errs.Handler(s.createInvitation).ServeHTTP)
	r.With(edge.Workspace).Post(httpx.WorkspacePrefix+"/api-keys/", errs.Handler(s.createAPIKey).ServeHTTP)
}

func principal(ctx context.Context) (authn.Principal, error) {
	if c, ok := authn.CallerFrom(ctx); ok {
		return c.Principal, nil
	}
	p, ok := authn.PrincipalFrom(ctx)
	if !ok {
		return authn.Principal{}, authn.ErrNoPrincipal
	}
	return p, nil
}

func caller(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// utcISO is utc_isoformat: a naive timestamp read as UTC, with a Z.
func utcISO(t time.Time) string {
	t = t.UTC()
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += "." + leftPad(strconv.Itoa(us), 6)
	}
	return s + "Z"
}

func leftPad(s string, n int) string {
	for len(s) < n {
		s = "0" + s
	}
	return s
}

func utcISOPtr(t *time.Time) any {
	if t == nil {
		return nil
	}
	return utcISO(*t)
}

func writeJSON(w http.ResponseWriter, status int, body wirejson.Object) error {
	raw, err := wirejson.Marshal(body, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(status)
	_, err = w.Write(raw)
	return err
}

// body reads and validates a JSON body after the route's dependencies ran.
func body(r *http.Request, validate func(o wirejson.Object, errs *[]httpx.FieldError)) error {
	v, err := readBody(r)
	if err != nil {
		return err
	}
	var errs []httpx.FieldError
	if o, ok := model(v, &errs); ok {
		validate(o, &errs)
	}
	return httpx.Validation(errs...)
}

// MaxName is the 255-character bound on workspace and key names.
const MaxName = 255

func (s *Server) createWorkspace(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	if err := authn.EnsureScope(p, authn.ScopeWorkspaces, "create workspaces"); err != nil {
		return err
	}
	var name string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		v, set := str(o, "name", 1, MaxName, false, errs)
		if !set {
			*errs = append(*errs, httpx.Missing("body", "name"))
		} else if v != nil {
			name = *v
		}
	})
	if err != nil {
		return err
	}
	name = pyStrip(name)
	if name == "" {
		return domain.ErrEmptyWorkspaceName
	}
	ws, err := s.svc.CreateWorkspace(r.Context(), p.UserID, name)
	if err != nil {
		return err
	}
	var logo any
	return writeJSON(w, http.StatusCreated, wirejson.Object{
		{Key: "id", Value: ws.ID}, {Key: "slug", Value: ws.Slug}, {Key: "name", Value: ws.Name},
		{Key: "owner_user_id", Value: ws.OwnerUserID}, {Key: "can_administer", Value: true}, {Key: "logo_url", Value: logo},
	})
}

// InvitationEmailPattern and InvitationEmailMaxLength bound an invitation's email.
const (
	InvitationEmailPattern   = `^[^\s@]+@[^\s@]+\.[^\s@]+$`
	InvitationEmailMaxLength = 320
	MaxInvitationDays        = 365
	MaxAPIKeyDays            = 3650
)

func (s *Server) createInvitation(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := s.edge.Admin(r.Context()); err != nil {
		return err
	}
	var email *string
	var days *int
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		v, _ := str(o, "email", 0, InvitationEmailMaxLength, true, errs)
		if v != nil {
			if validEmail(*v) {
				email = v
			} else {
				*errs = append(*errs, httpx.StringPatternMismatch(InvitationEmailPattern, "body", "email"))
			}
		}
		days, _ = intField(o, "expires_in_days", 1, MaxInvitationDays, errs)
	})
	if err != nil {
		return err
	}
	inv, err := s.svc.CreateInvitation(r.Context(), c, email, days)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusCreated, wirejson.Object{
		{Key: "id", Value: inv.ID},
		{Key: "workspace_id", Value: inv.WorkspaceID},
		{Key: "email", Value: inv.Email},
		{Key: "invited_by", Value: inv.InvitedBy},
		{Key: "invited_by_display_name", Value: inv.InviterDisplayName},
		{Key: "status", Value: inv.Status},
		{Key: "expires_at", Value: utcISO(inv.ExpiresAt)},
		{Key: "accepted_at", Value: utcISOPtr(inv.AcceptedAt)},
		{Key: "accepted_by_user_id", Value: inv.AcceptedByUserID},
		{Key: "created_at", Value: utcISO(inv.CreatedAt)},
		{Key: "token", Value: inv.Token},
		{Key: "email_delivery", Value: string(inv.EmailDelivery)},
	})
}

func (s *Server) acceptInvitation(w http.ResponseWriter, r *http.Request) error {
	p, err := principal(r.Context())
	if err != nil {
		return err
	}
	if err := authn.EnsureScope(p, authn.ScopeWorkspaces, "join workspaces"); err != nil {
		return err
	}
	var token string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		v, set := str(o, "token", 0, 0, false, errs)
		if !set {
			*errs = append(*errs, httpx.Missing("body", "token"))
		} else if v != nil {
			token = *v
		}
	})
	if err != nil {
		return err
	}
	inv, err := s.svc.AcceptInvitation(r.Context(), p, token)
	if err != nil {
		return err
	}
	return writeJSON(w, http.StatusOK, wirejson.Object{
		{Key: "workspace_id", Value: inv.WorkspaceID}, {Key: "user_id", Value: p.UserID}, {Key: "invitation_id", Value: inv.ID},
	})
}

func (s *Server) createAPIKey(w http.ResponseWriter, r *http.Request) error {
	c, err := caller(r.Context())
	if err != nil {
		return err
	}
	if err := authn.EnsureScope(c.Principal, authn.ScopeCredentials, "create API keys"); err != nil {
		return err
	}
	var name string
	var days *int
	var agent *string
	err = body(r, func(o wirejson.Object, errs *[]httpx.FieldError) {
		v, set := str(o, "name", 1, MaxName, false, errs)
		if !set {
			*errs = append(*errs, httpx.Missing("body", "name"))
		} else if v != nil {
			name = *v
		}
		days, _ = intField(o, "expires_in_days", 1, MaxAPIKeyDays, errs)
		agent, _ = uuidField(o, "agent_id", errs)
	})
	if err != nil {
		return err
	}
	k, err := s.svc.CreateAPIKey(r.Context(), c, name, days, agent)
	if err != nil {
		return err
	}
	var agentID any
	if k.AgentID != nil {
		agentID = *k.AgentID
	}
	return writeJSON(w, http.StatusCreated, wirejson.Object{
		{Key: "id", Value: k.ID},
		{Key: "name", Value: k.Name},
		{Key: "token_prefix", Value: k.TokenPrefix},
		{Key: "is_active", Value: k.IsActive},
		{Key: "expires_at", Value: utcISOPtr(k.ExpiresAt)},
		{Key: "access_count", Value: k.AccessCount},
		{Key: "last_accessed_at", Value: utcISOPtr(k.LastAccessedAt)},
		{Key: "created_at", Value: utcISO(k.CreatedAt)},
		{Key: "agent_id", Value: agentID},
		{Key: "token", Value: k.Token},
	})
}

// validEmail matches InvitationEmailPattern with Unicode \s, as pydantic's
// regex engine reads it.
func validEmail(s string) bool {
	if strings.IndexFunc(s, unicode.IsSpace) >= 0 || strings.Count(s, "@") != 1 {
		return false
	}
	local, domain, _ := strings.Cut(s, "@")
	if local == "" {
		return false
	}
	for i := 1; i < len(domain)-1; i++ {
		if domain[i] == '.' {
			return true
		}
	}
	return false
}
