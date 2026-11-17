package handlers

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type memRules struct{ rows []domain.Rule }

func (m *memRules) List(context.Context, db.Session, store.Filter) ([]domain.Rule, error) {
	return m.rows, nil
}

func (m *memRules) Get(_ context.Context, _ db.Session, id uuid.UUID) (domain.Rule, bool, error) {
	for _, r := range m.rows {
		if r.ID == id.String() {
			return r, true, nil
		}
	}
	return domain.Rule{}, false, nil
}

func (m *memRules) Create(_ context.Context, _ db.Session, id uuid.UUID, _ string, r domain.Rule, _ time.Time) (domain.Rule, error) {
	r.ID = id.String()
	m.rows = append(m.rows, r)
	return r, nil
}

func (m *memRules) Update(_ context.Context, _ db.Session, id uuid.UUID, p store.Patch, _ time.Time) (domain.Rule, bool, error) {
	for i, r := range m.rows {
		if r.ID == id.String() {
			if p.Priority != nil {
				r.Priority = *p.Priority
			}
			m.rows[i] = r
			return r, true, nil
		}
	}
	return domain.Rule{}, false, nil
}

func (m *memRules) Delete(_ context.Context, _ db.Session, id uuid.UUID) (bool, error) {
	for i, r := range m.rows {
		if r.ID == id.String() {
			m.rows = append(m.rows[:i], m.rows[i+1:]...)
			return true, nil
		}
	}
	return false, nil
}

type memAudit struct{ events []domain.AuditEvent }

func (m *memAudit) Insert(_ context.Context, _ db.Querier, e domain.AuditEvent, now time.Time) error {
	e.CreatedAt = now
	if e.Changes != nil {
		e.RawChanges, _ = json.Marshal(e.Changes)
	}
	e.RawMetadata, _ = json.Marshal(e.Metadata)
	m.events = append([]domain.AuditEvent{e}, m.events...)
	return nil
}

func (m *memAudit) InsertOnce(context.Context, db.Querier, domain.AuditEvent) (bool, error) {
	return true, nil
}

func (m *memAudit) ResourcePage(context.Context, db.Session, string, []string, int, int) ([]domain.AuditEvent, int64, error) {
	return m.events, int64(len(m.events)), nil
}

func (m *memAudit) Query(_ context.Context, _ db.Session, q domain.AuditQuery) ([]domain.AuditEvent, error) {
	if q.Cursor != nil {
		return nil, store.ErrUnknownCursor
	}
	return m.events[:min(q.Limit, len(m.events))], nil
}

type env struct {
	srv     *httptest.Server
	isAdmin *bool
}

func newEnv(t *testing.T) env {
	t.Helper()
	ws, err := scope.NewWorkspace(uuid.NewString(), "acme")
	if err != nil {
		t.Fatal(err)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), caller)))
		})
	}
	isAdmin := true
	admin := func(context.Context) error {
		if isAdmin {
			return nil
		}
		return httpx.HTTPError(http.StatusForbidden, "Workspace admin required")
	}
	svc := service.New(service.Deps{DB: fakeDB{}, Policies: &memRules{}, Audit: &memAudit{}, Log: slog.New(slog.DiscardHandler),
		Now: func() time.Time { return time.Date(2026, 5, 1, 10, 0, 0, 0, time.UTC) }})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, admin, New(svc, admin), Routes{})
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return env{srv: s, isAdmin: &isAdmin}
}

func (e env) call(t *testing.T, method, path, body string) (int, string) {
	t.Helper()
	req, err := http.NewRequest(method, e.srv.URL+"/v1/workspaces/acme"+path, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, _ := io.ReadAll(resp.Body)
	return resp.StatusCode, string(raw)
}

func TestPolicyRuleLifecycle(t *testing.T) {
	e := newEnv(t)
	status, body := e.call(t, http.MethodPost, "/policies", `{"subject_type":"workspace","subject_id":"w","target":"spend","effect":"cap","params":{"period":"month","amount_usd":"10.00"}}`)
	if status != http.StatusCreated {
		t.Fatalf("%d %s", status, body)
	}
	var created map[string]any
	if err := json.Unmarshal([]byte(body), &created); err != nil {
		t.Fatal(err)
	}
	id := created["id"].(string)
	want := `{"id":"` + id + `","enabled":true,"priority":0,"subject_type":"workspace","subject_id":"w","target":"spend","effect":"cap","params":{"period":"month","amount_usd":"10.00"},"condition":null}`
	if body != want {
		t.Fatalf("body %s", body)
	}
	if status, got := e.call(t, http.MethodGet, "/policies/"+strings.ToUpper(id), ""); status != http.StatusOK || !strings.Contains(got, `"id":"`+id+`"`) {
		t.Fatalf("get %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodPatch, "/policies/"+id, `{"priority":5}`); status != http.StatusOK || !strings.Contains(got, `"priority":5`) {
		t.Fatalf("patch %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodPatch, "/policies/"+id, `{"target":null}`); status != http.StatusUnprocessableEntity || !strings.Contains(got, "invalid target selector None") {
		t.Fatalf("null target %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodGet, "/policies", ""); status != http.StatusOK || !strings.HasPrefix(got, `[{"id":"`+id) {
		t.Fatalf("list %d %s", status, got)
	}
	if status, _ := e.call(t, http.MethodDelete, "/policies/"+id, ""); status != http.StatusNoContent {
		t.Fatalf("delete %d", status)
	}
	if status, got := e.call(t, http.MethodDelete, "/policies/"+id, ""); status != http.StatusNotFound || !strings.Contains(got, "Policy rule not found") {
		t.Fatalf("delete again %d %s", status, got)
	}
	if status, got := e.call(t, http.MethodGet, "/audit-logs/", ""); status != http.StatusOK ||
		!strings.Contains(got, `"action":"governance_policy.delete"`) || !strings.Contains(got, `"created_at":"2026-05-01T10:00:00Z"`) || !strings.Contains(got, `"next_cursor":null`) {
		t.Fatalf("audit %d %s", status, got)
	}
}

func TestPolicyValidation(t *testing.T) {
	e := newEnv(t)
	for _, c := range []struct{ method, path, body, want string }{
		{http.MethodPost, "/policies", `{"subject_type":"team","subject_id":"w","target":"x","effect":"deny"}`, `"type":"enum"`},
		{http.MethodPost, "/policies", `{"subject_id":"w","target":"x","effect":"deny"}`, `"type":"missing","loc":["body","subject_type"]`},
		{http.MethodPost, "/policies", `{"subject_type":"workspace","subject_id":"w","target":"tool:x","effect":"deny","color":1}`, `"type":"extra_forbidden"`},
		{http.MethodPost, "/policies", `{"subject_type":"workspace","subject_id":"w","target":"tool:x","effect":"deny","priority":2147483648}`, `"type":"less_than_equal"`},
		{http.MethodPost, "/policies", `{"subject_type":"workspace","subject_id":"w","target":"tool:x","effect":"deny","params":[]}`, `"type":"dict_type"`},
		{http.MethodPost, "/policies", `{"subject_type":"workspace","subject_id":"w","target":"tool:*","effect":"deny"}`, `not a wildcard`},
		{http.MethodGet, "/policies/not-a-uuid", ``, `"type":"uuid_parsing"`},
		{http.MethodGet, "/policies?effect=nope", ``, `"type":"enum"`},
		{http.MethodGet, "/audit-logs/?limit=0", ``, `"type":"greater_than_equal"`},
		{http.MethodGet, "/audit-logs/?since=yesterday", ``, `"type":"datetime_from_date_parsing"`},
		{http.MethodPost, "/governance/effective-policy/preview", `{"agent_id":"x"}`, `"type":"uuid_parsing"`},
		{http.MethodPost, "/governance/effective-policy/preview", `{"task_policy":{"budget":{"run_budget_usd":"-1"}}}`, `"loc":["body","task_policy","budget","run_budget_usd"]`},
	} {
		status, body := e.call(t, c.method, c.path, c.body)
		if status != http.StatusUnprocessableEntity || !strings.Contains(body, c.want) {
			t.Errorf("%s %s %s: %d %s", c.method, c.path, c.body, status, body)
		}
	}
}

func TestAdminOrdering(t *testing.T) {
	e := newEnv(t)
	*e.isAdmin = false
	// requires_workspace_admin routes refuse before validating.
	for _, c := range []struct{ method, path string }{
		{http.MethodGet, "/policies?effect=nope"},
		{http.MethodGet, "/policies/not-a-uuid"},
		{http.MethodGet, "/audit-logs/?limit=0"},
	} {
		if status, body := e.call(t, c.method, c.path, ""); status != http.StatusForbidden {
			t.Errorf("%s %s: %d %s", c.method, c.path, status, body)
		}
	}
	// Mutations validate first, then check the caller.
	if status, _ := e.call(t, http.MethodPost, "/policies", `{}`); status != http.StatusUnprocessableEntity {
		t.Errorf("create validates first: %d", status)
	}
	if status, _ := e.call(t, http.MethodPost, "/policies", `{"subject_type":"workspace","subject_id":"w","target":"tool:x","effect":"deny"}`); status != http.StatusForbidden {
		t.Errorf("create by non-admin: %d", status)
	}
	if status, _ := e.call(t, http.MethodDelete, "/policies/"+uuid.NewString(), ""); status != http.StatusForbidden {
		t.Errorf("delete by non-admin: %d", status)
	}
	// The preview needs no admin.
	if status, body := e.call(t, http.MethodPost, "/governance/effective-policy/preview", `{}`); status != http.StatusOK || !strings.HasPrefix(body, `{"effective_policy":{`) {
		t.Errorf("preview %d %s", status, body)
	}
}

func TestAuditCursorAndEgressAndUnmountedRoutes(t *testing.T) {
	e := newEnv(t)
	c := uuid.NewString()
	if status, body := e.call(t, http.MethodGet, "/audit-logs/?cursor="+c, ""); status != http.StatusBadRequest || !strings.Contains(body, "Unknown audit cursor "+c) {
		t.Fatalf("cursor %d %s", status, body)
	}
	for _, m := range []string{http.MethodGet, http.MethodPost} {
		if status, body := e.call(t, m, "/egress-exits/", `{}`); status != http.StatusNotFound || !strings.Contains(body, EgressDetail) {
			t.Fatalf("egress %s %d %s", m, status, body)
		}
	}
	if status, _ := e.call(t, http.MethodGet, "/egress-exits/not-a-uuid", ""); status != http.StatusNotFound {
		t.Fatalf("egress gate runs before path validation: %d", status)
	}
	if status, _ := e.call(t, http.MethodGet, "/secrets", ""); status != http.StatusNotFound && status != http.StatusMethodNotAllowed {
		t.Fatalf("secrets mounted without a catalog: %d", status)
	}
}

func TestParseDatetime(t *testing.T) {
	for in, want := range map[string]string{
		"2026-01-02":                  "2026-01-02T00:00:00Z",
		"2026-01-02T03:04:05":         "2026-01-02T03:04:05Z",
		"2026-01-02T03:04:05.5+02:00": "2026-01-02T01:04:05.500000Z",
		"2026-01-02 03:04Z":           "2026-01-02T03:04:00Z",
		"1700000000":                  "2023-11-14T22:13:20Z",
	} {
		got, ok := parseDatetime(in)
		if !ok || utcISO(got) != want {
			t.Errorf("parseDatetime(%q) = %v %v, want %s", in, utcISO(got), ok, want)
		}
	}
	for _, bad := range []string{"", "2026-02-30", "2026-13-01", "yesterday", "2026-01-02T25:00"} {
		if _, ok := parseDatetime(bad); ok {
			t.Errorf("parseDatetime(%q) accepted", bad)
		}
	}
}
