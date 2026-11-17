package handlers

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/service"
)

var errNotAdmin = errors.New("not admin")

// server mounts the routes over a service with no adapters: every request
// here is refused before the service runs.
func server(t *testing.T, kind authn.CredentialKind, admin bool) *httptest.Server {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	p := authn.Principal{UserID: "owner", Credential: &authn.Credential{Kind: kind}}
	edge := Edge{
		Workspace: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), authn.Caller{Principal: p, Workspace: ws})))
			})
		},
		Principal: func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				next.ServeHTTP(w, r.WithContext(authn.WithPrincipal(r.Context(), p)))
			})
		},
		Admin: func(context.Context) error {
			if admin {
				return nil
			}
			return errNotAdmin
		},
	}
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError, func(err error) (*httpx.Error, bool) {
		var scopeErr *authn.ScopeRequiredError
		switch {
		case errors.Is(err, errNotAdmin):
			return httpx.HTTPError(http.StatusForbidden, "admin"), true
		case errors.As(err, &scopeErr):
			return httpx.Forbidden(scopeErr.Error()), true
		}
		return nil, false
	})
	r := chi.NewRouter()
	Mount(r, errs, edge, service.New(service.Deps{}, nil))
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s
}

func post(t *testing.T, s *httptest.Server, path, body string) (int, string) {
	t.Helper()
	resp, err := http.Post(s.URL+path, "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(raw)
}

func TestValidation(t *testing.T) {
	s := server(t, authn.KindSession, true)
	for _, c := range []struct{ path, body, status, want string }{
		{"/v1/workspaces", `{"name":"   "}`, "422", `"detail":"Workspace name must not be empty"`},
		{"/v1/workspaces", `{"name":""}`, "422", `"type":"string_too_short"`},
		{"/v1/workspaces", `{}`, "422", `"type":"missing"`},
		{"/v1/invitations/accept", `{"token":5}`, "422", `"type":"string_type"`},
		{"/v1/workspaces/acme/invitations", `{"email":"not an email"}`, "422", `"type":"string_pattern_mismatch"`},
		{"/v1/workspaces/acme/invitations", `{"expires_in_days":366}`, "422", `"type":"less_than_equal"`},
		{"/v1/workspaces/acme/invitations", `{"expires_in_days":1.5}`, "422", `"type":"int_from_float"`},
		{"/v1/workspaces/acme/api-keys/", `{"name":"k","agent_id":"x"}`, "422", `"type":"uuid_parsing"`},
		{"/v1/workspaces/acme/api-keys/", `{"name":"k","expires_in_days":0}`, "422", `"type":"greater_than_equal"`},
	} {
		status, body := post(t, s, c.path, c.body)
		if strconv.Itoa(status) != c.status || !strings.Contains(body, c.want) {
			t.Errorf("%s %s: %d %s", c.path, c.body, status, body)
		}
	}
}

func TestAPIKeyCredentialsCannotMintCredentialsOrWorkspaces(t *testing.T) {
	s := server(t, authn.KindAPIKey, true)
	for path, want := range map[string]string{
		"/v1/workspaces":                "This credential cannot create workspaces; sign in as a user to do it",
		"/v1/invitations/accept":        "This credential cannot join workspaces; sign in as a user to do it",
		"/v1/workspaces/acme/api-keys/": "This credential cannot create API keys; sign in as a user to do it",
	} {
		status, body := post(t, s, path, `{}`)
		if status != http.StatusForbidden || !strings.Contains(body, want) {
			t.Errorf("%s: %d %s", path, status, body)
		}
	}
}

func TestInvitationNeedsAnAdminBeforeTheBodyIsRead(t *testing.T) {
	s := server(t, authn.KindSession, false)
	status, body := post(t, s, "/v1/workspaces/acme/invitations", `{"email":"bad"}`)
	if status != http.StatusForbidden || !strings.Contains(body, `"detail":"admin"`) {
		t.Fatalf("%d %s", status, body)
	}
}

func TestValidEmail(t *testing.T) {
	for in, want := range map[string]bool{
		"a@b.co": true, "a@b.c.d": true, "a@.co": false, "a@b..co": true, "a@..": false, "@b.co": false, "a@b": false,
		"a@b.": false, "a b@c.de": false, "a@b@c.de": false, "a @b.co": false,
	} {
		if validEmail(in) != want {
			t.Errorf("validEmail(%q) = %v", in, !want)
		}
	}
}
