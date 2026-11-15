package handlers

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/service"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func quiet() *slog.Logger { return slog.New(slog.NewTextHandler(io.Discard, nil)) }

func router(t *testing.T) http.Handler {
	return routerWith(t, func(context.Context, string) error { return nil })
}

func routerWith(t *testing.T, authority func(context.Context, string) error) http.Handler {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	workspace := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			c := authn.Caller{Principal: authn.Principal{UserID: "user-1"}, Workspace: ws}
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), c)))
		})
	}
	s := service.NewSurface(service.SurfaceDeps{DB: fakeDB{}, AppURL: "http://app", Log: quiet()})
	r := chi.NewRouter()
	srv := New(s, nil)
	srv.authority = authority
	Mount(r, httpx.NewErrors("http://api", quiet(), MapError, edgeAdmin), workspace, srv)
	return r
}

func call(t *testing.T, h http.Handler, method, path, body string) (int, string) {
	t.Helper()
	var rd io.Reader
	if body != "" {
		rd = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, rd)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

func TestQueryAndBodyErrorsAreOne422(t *testing.T) {
	h := router(t)
	agent, task := uuid.NewString(), uuid.NewString()
	base := "/v1/workspaces/acme/agents/" + agent + "/tasks/" + task
	for _, c := range []struct {
		method, path, body string
		want               []string
	}{
		{"GET", "/v1/workspaces/acme/inbox/?status=running&page_size=201", "", []string{`"literal_error"`, `"page_size"`, `"less_than_equal"`}},
		{"GET", "/v1/workspaces/acme/tasks/?status=done&limit=0", "", []string{`["query","status",0]`, `"greater_than_equal"`}},
		{"GET", base + "/events?page_size=101", "", []string{`"less_than_equal"`}},
		{"GET", base + "/events/stream?include_chunks=maybe", "", []string{`"bool_parsing"`}},
		{"POST", base + "/resolve-escalation", `{"approved":"perhaps"}`, []string{`"escalation_id"`, `"bool_parsing"`}},
		{"GET", "/v1/workspaces/acme/tool-call-approvals?status=open", "", []string{`"enum"`}},
		{"GET", "/v1/workspaces/acme/agents/nope/tasks/", "", []string{`"uuid_parsing"`}},
	} {
		code, body := call(t, h, c.method, c.path, c.body)
		if code != http.StatusUnprocessableEntity {
			t.Errorf("%s %s: %d %s", c.method, c.path, code, body)
			continue
		}
		for _, w := range c.want {
			if !strings.Contains(body, w) {
				t.Errorf("%s %s: %s lacks %s", c.method, c.path, body, w)
			}
		}
	}
}

func TestInputBodyNamesBothUnionBranches(t *testing.T) {
	h := router(t)
	path := "/v1/workspaces/acme/agents/" + uuid.NewString() + "/tasks/" + uuid.NewString() + "/command"
	code, body := call(t, h, "POST", path, `{"command":"update_budget","budget_usd":"1e"}`)
	if code != http.StatusUnprocessableEntity || !strings.Contains(body, `Value error, '1e' is not a money amount`) {
		t.Fatalf("%d %s", code, body)
	}
}

func TestAnApprovalIdThatIsNoUUIDIsNotFound(t *testing.T) {
	code, body := call(t, router(t), "GET", "/v1/workspaces/acme/tool-call-approvals/not-an-id", "")
	if code != http.StatusNotFound || !strings.Contains(body, "Approval not found") {
		t.Fatalf("%d %s", code, body)
	}
}

func TestDecideIsUnmountedWithoutTheAuditWriter(t *testing.T) {
	code, _ := call(t, router(t), "POST", "/v1/workspaces/acme/tool-call-approvals/"+uuid.NewString()+"/decide", `{"approved":true}`)
	if code != http.StatusNotFound && code != http.StatusMethodNotAllowed {
		t.Fatalf("decide answered %d", code)
	}
}

func TestMoneyOfRefusesBoolsAndJunk(t *testing.T) {
	for _, v := range []any{true, "abc", "١٢"} {
		var nm notMoney
		if _, err := moneyOf(v); !errors.As(err, &nm) {
			t.Errorf("moneyOf(%v) = %v", v, err)
		}
	}
	if d, err := moneyOf(" 2.50 "); err != nil || d.String() != "2.50" {
		t.Fatalf("2.50: %v %v", d, err)
	}
}

func TestTaskAuthorityAnswersBeforeTheBodyIsRead(t *testing.T) {
	h := routerWith(t, func(context.Context, string) error { return authz.ErrNotWorkspaceAdmin })
	path := "/v1/workspaces/acme/agents/" + uuid.NewString() + "/tasks/" + uuid.NewString() + "/command"
	code, body := call(t, h, "POST", path, `[]`)
	if code != http.StatusForbidden || !strings.Contains(body, "Only a workspace admin may perform this action") {
		t.Fatalf("%d %s", code, body)
	}
}

// edgeAdmin is the edge's mapping of a refused admin check.
func edgeAdmin(err error) (*httpx.Error, bool) {
	if errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		return httpx.HTTPError(http.StatusForbidden, authz.NotAdminDetail), true
	}
	return nil, false
}
