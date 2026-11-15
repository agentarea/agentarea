package handlers

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/api/contract"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/service/servicetest"
)

const wsID = "11111111-1111-1111-1111-111111111111"

type fakeDB struct{ db.Database }

func (fakeDB) Read(_ context.Context, ws scope.Workspace) (db.Session, func(), error) {
	return db.NewSession(ws, nil), func() {}, nil
}

func (fakeDB) Write(ctx context.Context, ws scope.Workspace, fn func(context.Context, db.Session) error) error {
	return fn(ctx, db.NewTxSession(ws, nil))
}

type events struct{ evs []domain.ArtifactEvent }

func (e *events) Insert(_ context.Context, _ db.Session, ev domain.ArtifactEvent) error {
	e.evs = append(e.evs, ev)
	return nil
}

func (e *events) Rename(_ context.Context, _ db.Session, source, destination string, _ time.Time) error {
	for i := range e.evs {
		if e.evs[i].Path == source {
			e.evs[i].Path = destination
		}
	}
	return nil
}

func (e *events) History(_ context.Context, _ db.Session, path string) ([]domain.ArtifactEvent, error) {
	var out []domain.ArtifactEvent
	for i := len(e.evs) - 1; i >= 0; i-- {
		if e.evs[i].Path == path {
			out = append(out, e.evs[i])
		}
	}
	return out, nil
}

type noProjects struct{}

func (noProjects) IDs(context.Context, scope.Workspace) ([]string, error) { return nil, nil }

func server(t *testing.T) (*httptest.Server, *servicetest.MemStore) {
	t.Helper()
	ws, err := scope.NewWorkspace(wsID, "acme")
	if err != nil {
		t.Fatal(err)
	}
	caller := authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
	admit := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			next.ServeHTTP(w, r.WithContext(authn.WithCaller(r.Context(), caller)))
		})
	}
	st := servicetest.NewMemStore()
	svc := service.New(service.Deps{DB: fakeDB{}, Events: &events{}, Projects: noProjects{}, Blob: st, APIURL: "http://api"})
	errs := httpx.NewErrors("http://api", slog.New(slog.DiscardHandler), MapError)
	r := chi.NewRouter()
	Mount(r, errs, admit, New(svc))
	s := httptest.NewServer(r)
	t.Cleanup(s.Close)
	return s, st
}

func call(t *testing.T, s *httptest.Server, method, path, body string) (*http.Response, string) {
	t.Helper()
	req, err := http.NewRequest(method, s.URL+"/v1/workspaces/acme"+path, strings.NewReader(body))
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
	return resp, string(raw)
}

func seed(t *testing.T, st *servicetest.MemStore, path, data string) {
	t.Helper()
	sum := sha256.Sum256([]byte(data))
	digest := hex.EncodeToString(sum[:])
	if err := st.Put(context.Background(), "workspaces/"+wsID+"/"+path, strings.NewReader(data), int64(len(data)), blob.PutOptions{
		ContentType: domain.ContentTypeOf(path), Metadata: map[string]string{"sha256": digest}, SHA256: digest,
	}); err != nil {
		t.Fatal(err)
	}
}

func TestListAndDirectories(t *testing.T) {
	s, st := server(t)
	seed(t, st, "a.txt", "a")
	resp, body := call(t, s, http.MethodPost, "/files/directories", `{"path":"docs/"}`)
	if resp.StatusCode != http.StatusCreated || body != `{"path":"docs/"}` {
		t.Fatalf("mkdir = %d %s", resp.StatusCode, body)
	}
	resp, body = call(t, s, http.MethodGet, "/files", "")
	want := `{"files":[{"path":"a.txt","size":1,"content_type":"text/plain","last_modified":"2026-11-12T10:00:00+00:00"}],"directories":["docs/"],"truncated":false}`
	if resp.StatusCode != http.StatusOK || body != want {
		t.Fatalf("list = %d %s", resp.StatusCode, body)
	}
}

func TestBodyValidation(t *testing.T) {
	s, _ := server(t)
	for _, c := range []struct{ path, body, has string }{
		{"/files/directories", `{"path":"","x":1}`, `"loc":["body","x"]`},
		{"/files/directories", `{}`, `"type":"missing"`},
		{"/files/move", `{"source":"a"}`, `"loc":["body","destination"]`},
		{"/files/upload-url", `{"filename":"a","content_type":"b","sha256":"c","size":"x"}`, `"type":"int_parsing"`},
		{"/files/upload-urls", `{"files":[]}`, `"type":"too_short"`},
		{"/files/upload-urls", `{"files":[{"path":1,"sha256":"a"}]}`, `"loc":["body","files",0,"path"]`},
	} {
		resp, body := call(t, s, http.MethodPost, c.path, c.body)
		if resp.StatusCode != http.StatusUnprocessableEntity || !strings.Contains(body, c.has) {
			t.Fatalf("%s %s = %d %s", c.path, c.body, resp.StatusCode, body)
		}
	}
	resp, body := call(t, s, http.MethodGet, "/files/history", "")
	if resp.StatusCode != http.StatusUnprocessableEntity || !strings.Contains(body, `"loc":["query","path"]`) {
		t.Fatalf("history = %d %s", resp.StatusCode, body)
	}
}

func TestDeleteRestoreHistory(t *testing.T) {
	s, st := server(t)
	seed(t, st, "dir/a b.txt", "x")
	resp, body := call(t, s, http.MethodDelete, "/files/dir/a%20b.txt", "")
	if resp.StatusCode != http.StatusOK || !strings.HasPrefix(body, `{"path":"dir/a b.txt","archived_path":".trash/`) {
		t.Fatalf("delete = %d %s", resp.StatusCode, body)
	}
	var archived struct {
		ArchivedPath string `json:"archived_path"`
	}
	_ = json.Unmarshal([]byte(body), &archived)
	resp, body = call(t, s, http.MethodPost, "/files/restore/"+strings.ReplaceAll(archived.ArchivedPath, " ", "%20"), "")
	if resp.StatusCode != http.StatusOK || !strings.Contains(body, `"archived_current":null`) {
		t.Fatalf("restore = %d %s", resp.StatusCode, body)
	}
	resp, body = call(t, s, http.MethodGet, "/files/history?path=/dir/a%20b.txt", "")
	if resp.StatusCode != http.StatusOK || !strings.HasPrefix(body, `{"path":"dir/a b.txt","events":[{"action":"archived","actor_type":"user","created_by":"owner"`) {
		t.Fatalf("history = %d %s", resp.StatusCode, body)
	}
	resp, body = call(t, s, http.MethodDelete, "/files/tasks/x", "")
	if resp.StatusCode != http.StatusBadRequest || !strings.Contains(body, `'tasks/x' is not a workspace library file`) {
		t.Fatalf("reserved = %d %s", resp.StatusCode, body)
	}
	resp, _ = call(t, s, http.MethodDelete, "/files/apps/x", "")
	if resp.StatusCode != http.StatusForbidden {
		t.Fatalf("apps = %d", resp.StatusCode)
	}
}

func TestDownloadAndURL(t *testing.T) {
	s, st := server(t)
	seed(t, st, "r/é.html", "<b>")
	resp, body := call(t, s, http.MethodGet, "/files/download/r/%C3%A9.html", "")
	if resp.StatusCode != http.StatusOK || body != "<b>" {
		t.Fatalf("download = %d %s", resp.StatusCode, body)
	}
	h := resp.Header
	if h.Get("Content-Type") != "text/html; charset=utf-8" || h.Get("Content-Length") != "3" || h.Get("X-Content-Type-Options") != "nosniff" ||
		h.Get("Content-Disposition") != `attachment; filename="e.html"; filename*=UTF-8''%C3%A9.html` {
		t.Fatalf("headers = %v", h)
	}
	resp, body = call(t, s, http.MethodGet, "/files/r/%C3%A9.html", "")
	if resp.StatusCode != http.StatusOK || body != `{"url":"http://api/v1/workspaces/acme/files/download/r/%C3%A9.html","path":"r/é.html"}` {
		t.Fatalf("url = %d %s", resp.StatusCode, body)
	}
	for _, p := range []string{"/files/download/missing", "/files/download/%0A", "/files/missing", "/files/", "/files/download/.trash/x"} {
		resp, body := call(t, s, http.MethodGet, p, "")
		if resp.StatusCode != http.StatusNotFound || !strings.Contains(body, "File not found") {
			t.Fatalf("%s = %d %s", p, resp.StatusCode, body)
		}
	}
	resp, body = call(t, s, http.MethodGet, "/files/a%0Ab", "")
	if resp.StatusCode != http.StatusNotFound || !strings.Contains(body, `"detail":"Not Found"`) {
		t.Fatalf("interior newline = %d %s", resp.StatusCode, body)
	}
}

func TestSandboxesUnconfigured(t *testing.T) {
	s, _ := server(t)
	resp, body := call(t, s, http.MethodGet, "/sandboxes", "")
	if resp.StatusCode != http.StatusServiceUnavailable || !strings.Contains(body, "Sandbox inventory is not configured") {
		t.Fatalf("sandboxes = %d %s", resp.StatusCode, body)
	}
}

// TestMountsEveryContractRoute: the files and sandboxes routes of the Python
// contract are all mounted, in chi's spelling.
func TestMountsEveryContractRoute(t *testing.T) {
	routes, err := contract.LoadRoutes()
	if err != nil {
		t.Fatal(err)
	}
	r := chi.NewRouter()
	Mount(r, httpx.NewErrors("http://api", slog.New(slog.DiscardHandler)), func(h http.Handler) http.Handler { return h }, New(nil))
	have := map[string]bool{}
	_ = chi.Walk(r, func(method, route string, _ http.Handler, _ ...func(http.Handler) http.Handler) error {
		have[method+" "+route] = true
		return nil
	})
	n := 0
	for _, rt := range routes.Routes {
		if rt.RouterFile != "apps/api/agentarea_api/api/v1/files.py" && rt.RouterFile != "apps/api/agentarea_api/api/v1/sandboxes.py" {
			continue
		}
		n++
		key := regexp.MustCompile(`\{\w+\.\.\.\}$`).ReplaceAllString(rt.Pattern(), "*")
		if !have[key] {
			t.Errorf("not mounted: %s", key)
		}
	}
	if n != 11 {
		t.Fatalf("contract routes = %d, want 11", n)
	}
}
