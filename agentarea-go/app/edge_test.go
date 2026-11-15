package app

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/serve"
)

// refusingGate refuses every request with the error it was given.
type refusingGate struct {
	authn.Gate
	err error
}

func (g refusingGate) Authenticate(context.Context, *http.Request) (authn.Principal, error) {
	return authn.Principal{}, g.err
}

func edgeServer(t *testing.T, err error) http.Handler {
	t.Helper()
	e := newEdge(refusingGate{err: err}, authz.Admins{})
	ok := serve.Module{Name: "ok", Mount: func(rt serve.Routes) error {
		rt.Mux.Chi().With(e.Workspace).Get("/v1/workspaces/{workspace}/things/", func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusOK)
		})
		return nil
	}}
	return assemble(t, e.module(), ok, slashRedirect())
}

func do(h http.Handler, method, target string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(method, target, nil))
	return rec
}

func TestSlashRedirectIsStarlettes(t *testing.T) {
	h := edgeServer(t, nil)
	rec := do(h, http.MethodPost, "http://api.test/v1/workspaces/acme/things?x=1")
	if rec.Code != http.StatusTemporaryRedirect || rec.Header().Get("Location") != "http://api.test/v1/workspaces/acme/things/?x=1" {
		t.Fatalf("%d %q", rec.Code, rec.Header().Get("Location"))
	}
	if rec := do(h, http.MethodGet, "http://api.test/v1/nothing"); rec.Code != http.StatusNotFound {
		t.Fatalf("unknown path: %d", rec.Code)
	}
}

func TestEdgeRendersRefusalsAsPythonDoes(t *testing.T) {
	refusal := &authn.Error{Status: http.StatusUnauthorized, Detail: "Missing credentials", WWWAuthenticate: `Bearer realm="x"`}
	rec := do(edgeServer(t, refusal), http.MethodGet, "http://api.test/v1/workspaces/acme/things/")
	body, _ := io.ReadAll(rec.Body)
	if rec.Code != http.StatusUnauthorized || rec.Header().Get("WWW-Authenticate") != `Bearer realm="x"` ||
		!strings.Contains(string(body), `"code":"http_error"`) || !strings.Contains(string(body), `"detail":"Missing credentials"`) {
		t.Fatalf("%d %v %s", rec.Code, rec.Header(), body)
	}
	for err, want := range map[error]string{
		&authn.ScopeRequiredError{Action: "create API keys"}: `"code":"permission_denied"`,
		authz.ErrNotWorkspaceAdmin:                           `"detail":"Only a workspace admin may perform this action"`,
		authz.ErrWorkspaceRequired:                           `"detail":"workspace_id is required"`,
	} {
		e, ok := edgeErrors(err)
		if !ok {
			t.Fatalf("%v not mapped", err)
		}
		raw, _ := e.Problem().Body()
		if !strings.Contains(string(raw), want) {
			t.Errorf("%v: %s", err, raw)
		}
	}
}
