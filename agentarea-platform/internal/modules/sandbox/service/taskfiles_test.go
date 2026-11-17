package service

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/service/servicetest"
)

type managerCall struct {
	path  string
	query url.Values
	auth  string
}

type fakeManager struct {
	mu    sync.Mutex
	calls []managerCall
	srv   *httptest.Server
}

func newFakeManager(t *testing.T, h http.HandlerFunc) *fakeManager {
	t.Helper()
	m := &fakeManager{}
	m.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		m.mu.Lock()
		m.calls = append(m.calls, managerCall{path: r.URL.Path, query: r.URL.Query(), auth: r.Header.Get("Authorization")})
		m.mu.Unlock()
		h(w, r)
	}))
	t.Cleanup(m.srv.Close)
	return m
}

func (m *fakeManager) last(t *testing.T) managerCall {
	t.Helper()
	m.mu.Lock()
	defer m.mu.Unlock()
	if len(m.calls) == 0 {
		t.Fatal("manager not called")
	}
	return m.calls[len(m.calls)-1]
}

func taskFilesOver(t *testing.T, managerURL, secret string) (api.TaskFiles, *servicetest.MemStore) {
	t.Helper()
	harness := servicetest.NewMemStore()
	f := newFixture(t, Deps{Manager: Manager{URL: managerURL, FileSecret: secret}, Harness: harness})
	return f.svc.TaskFiles(), harness
}

func wantTaskFileError(t *testing.T, err error, status int, detail string) {
	t.Helper()
	var te *api.TaskFileError
	if !errors.As(err, &te) || te.Status != status || te.Detail != detail {
		t.Fatalf("err = %v, want %d %q", err, status, detail)
	}
}

func wantQuery(t *testing.T, got url.Values, want map[string]string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("query = %v, want %v", got, want)
	}
	for k, v := range want {
		if got.Get(k) != v {
			t.Fatalf("query %s = %q, want %q (all %v)", k, got.Get(k), v, got)
		}
	}
}

func TestTaskFilesNotConfigured(t *testing.T) {
	m := newFakeManager(t, func(http.ResponseWriter, *http.Request) { t.Error("manager called") })
	tf, _ := taskFilesOver(t, m.srv.URL, "")
	ctx := context.Background()
	_, err := tf.Artifacts(ctx, wsID, taskID)
	wantTaskFileError(t, err, 503, "Sandbox file access is not configured")
	_, err = tf.Artifact(ctx, wsID, taskID, "art_"+strings.Repeat("a", 32))
	wantTaskFileError(t, err, 503, "Sandbox file access is not configured")
	_, err = tf.ListFiles(ctx, wsID, taskID, "", false)
	wantTaskFileError(t, err, 503, "Sandbox file access is not configured")
	_, err = tf.ReadFile(ctx, wsID, taskID, "a.txt", false)
	if !errors.Is(err, api.ErrTaskFilesNotConfigured) {
		t.Fatalf("read err = %v", err)
	}
}

func TestTaskArtifactsList(t *testing.T) {
	m := newFakeManager(t, func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, `{"items":[
			{"id":"art_1","path":"outputs/r.csv","name":"r.csv","size":12,"content_type":"text/csv","sha256":"ab","created_at":"2026-11-12T09:30:15.5Z"},
			{"id":"art_2","path":"outputs/x","name":"x","size":"3","created_at":null,"extra":1},
			{"id":"art_3","path":"outputs/y","name":"y","size":4.0,"content_type":"","created_at":"2026-11-12 09:30:15"}]}`)
	})
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	items, err := tf.Artifacts(context.Background(), wsID, taskID)
	if err != nil {
		t.Fatal(err)
	}
	c := m.last(t)
	if c.path != "/sandbox/artifacts" || c.auth != "Bearer "+fileKey {
		t.Fatalf("call = %+v", c)
	}
	wantQuery(t, c.query, map[string]string{"workspace_id": wsID, "task_id": taskID})
	if len(items) != 3 {
		t.Fatalf("items = %+v", items)
	}
	first := items[0]
	if first.ID != "art_1" || first.Path != "outputs/r.csv" || first.Name != "r.csv" || first.Size != 12 ||
		first.ContentType != "text/csv" || first.SHA256 != "ab" || first.CreatedAt == nil ||
		!first.CreatedAt.Equal(time.Date(2026, 11, 12, 9, 30, 15, 5e8, time.UTC)) {
		t.Fatalf("first = %+v", first)
	}
	if items[1].ContentType != "" || items[1].SHA256 != "" || items[1].CreatedAt != nil || items[1].Size != 3 {
		t.Fatalf("second = %+v", items[1])
	}
	if items[2].Size != 4 || items[2].CreatedAt == nil || !items[2].CreatedAt.Equal(time.Date(2026, 11, 12, 9, 30, 15, 0, time.UTC)) {
		t.Fatalf("third = %+v", items[2])
	}
}

func TestTaskArtifactsListStatusMapping(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status int
		body   string
		want   int
		detail string
	}{
		{"missing", 404, "", 404, "Artifact list not found"},
		{"expired", 410, "", 410, "Sandbox workspace has expired"},
		{"server error", 500, "boom", 503, "Sandbox file access is temporarily unavailable"},
		{"forbidden", 403, "", 503, "Sandbox file access is temporarily unavailable"},
		{"not json", 200, "nope", 502, "Artifact list response is invalid"},
		{"not an object", 200, `[]`, 502, "Artifact list response is invalid"},
		{"no items", 200, `{}`, 502, "Artifact list response is invalid"},
		{"null content type", 200, `{"items":[{"id":"a","path":"p","name":"n","size":1,"content_type":null}]}`, 502, "Artifact list response is invalid"},
		{"int id", 200, `{"items":[{"id":1,"path":"p","name":"n","size":1}]}`, 502, "Artifact list response is invalid"},
		{"fractional size", 200, `{"items":[{"id":"a","path":"p","name":"n","size":1.5}]}`, 502, "Artifact list response is invalid"},
		{"bad date", 200, `{"items":[{"id":"a","path":"p","name":"n","size":1,"created_at":"yesterday"}]}`, 502, "Artifact list response is invalid"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := newFakeManager(t, func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.status)
				_, _ = io.WriteString(w, tc.body)
			})
			tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
			_, err := tf.Artifacts(context.Background(), wsID, taskID)
			wantTaskFileError(t, err, tc.want, tc.detail)
		})
	}
}

func TestTaskFilesManagerUnreachable(t *testing.T) {
	m := newFakeManager(t, func(http.ResponseWriter, *http.Request) {})
	m.srv.Close()
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	_, err := tf.Artifacts(context.Background(), wsID, taskID)
	wantTaskFileError(t, err, 503, "Sandbox file access is temporarily unavailable")
	_, err = tf.ReadFile(context.Background(), wsID, taskID, "a.txt", false)
	wantTaskFileError(t, err, 503, "Sandbox file access is temporarily unavailable")
}

func TestTaskFilesRedirectNotFollowed(t *testing.T) {
	m := newFakeManager(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/elsewhere" {
			_, _ = io.WriteString(w, `{"items":[]}`)
			return
		}
		http.Redirect(w, r, "/elsewhere", http.StatusFound)
	})
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	_, err := tf.Artifacts(context.Background(), wsID, taskID)
	wantTaskFileError(t, err, 502, "Artifact list response is invalid")
}

func readDownload(t *testing.T, d api.Download) string {
	t.Helper()
	defer func() { _ = d.Body.Close() }()
	b, err := io.ReadAll(d.Body)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func TestTaskArtifactDownload(t *testing.T) {
	artID := "art_" + strings.Repeat("0", 32)
	m := newFakeManager(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Query().Get("task_id") {
		case "html":
			w.Header().Set("Content-Type", "text/html")
			w.Header().Set("Content-Disposition", "inline")
		case "bare":
			w.Header()["Content-Type"] = nil
		default:
			w.Header().Set("Content-Type", "application/pdf")
			w.Header().Set("Content-Disposition", `attachment; filename="r.pdf"`)
		}
		w.Header().Set("Content-Length", "5")
		_, _ = io.WriteString(w, "%PDF-")
	})
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	ctx := context.Background()
	d, err := tf.Artifact(ctx, wsID, taskID, artID)
	if err != nil {
		t.Fatal(err)
	}
	if body := readDownload(t, d); body != "%PDF-" {
		t.Fatalf("body = %q", body)
	}
	c := m.last(t)
	if c.path != "/sandbox/artifacts/"+artID || c.auth != "Bearer "+fileKey {
		t.Fatalf("call = %+v", c)
	}
	wantQuery(t, c.query, map[string]string{"workspace_id": wsID, "task_id": taskID})
	h := d.Header
	if h.Get("Content-Type") != "application/pdf" || h.Get("Content-Disposition") != `attachment; filename="r.pdf"` ||
		h.Get("X-Content-Type-Options") != "nosniff" || h.Get("Content-Length") != "5" {
		t.Fatalf("headers = %v", h)
	}

	d, err = tf.Artifact(ctx, wsID, "html", artID)
	if err != nil {
		t.Fatal(err)
	}
	_ = readDownload(t, d)
	if d.Header.Get("Content-Type") != "text/html; charset=utf-8" ||
		d.Header.Get("Content-Disposition") != `attachment; filename="`+artID+`"; filename*=UTF-8''`+artID {
		t.Fatalf("html headers = %v", d.Header)
	}

	d, err = tf.Artifact(ctx, wsID, "bare", artID)
	if err != nil {
		t.Fatal(err)
	}
	_ = readDownload(t, d)
	if d.Header.Get("Content-Type") != "application/octet-stream" ||
		!strings.HasPrefix(d.Header.Get("Content-Disposition"), `attachment; filename="`+artID+`"`) {
		t.Fatalf("bare headers = %v", d.Header)
	}
}

func TestTaskArtifactDownloadStatusMapping(t *testing.T) {
	for status, want := range map[int][2]string{
		404: {"404", "Artifact not found"},
		410: {"410", "Sandbox workspace has expired"},
		502: {"503", "Sandbox file access is temporarily unavailable"},
	} {
		m := newFakeManager(t, func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(status) })
		tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
		_, err := tf.Artifact(context.Background(), wsID, taskID, "art_"+strings.Repeat("1", 32))
		var te *api.TaskFileError
		if !errors.As(err, &te) || itoa(int64(te.Status)) != want[0] || te.Detail != want[1] {
			t.Fatalf("status %d: err = %v", status, err)
		}
	}
}

func TestTaskSandboxFileRead(t *testing.T) {
	m := newFakeManager(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Query().Get("path") {
		case "gone.txt":
			w.WriteHeader(410)
		case "missing.txt":
			w.WriteHeader(404)
		default:
			w.Header()["Content-Type"] = nil
			_, _ = io.WriteString(w, "a,b\n")
		}
	})
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	ctx := context.Background()
	d, err := tf.ReadFile(ctx, wsID, taskID, "outputs/report.csv", false)
	if err != nil {
		t.Fatal(err)
	}
	if body := readDownload(t, d); body != "a,b\n" {
		t.Fatalf("body = %q", body)
	}
	c := m.last(t)
	if c.path != "/sandbox/file-content" {
		t.Fatalf("call = %+v", c)
	}
	wantQuery(t, c.query, map[string]string{"workspace_id": wsID, "task_id": taskID, "path": "outputs/report.csv", "ensure": "false"})
	if d.Header.Get("Content-Type") != "text/csv; charset=utf-8" ||
		d.Header.Get("Content-Disposition") != `attachment; filename="report.csv"; filename*=UTF-8''report.csv` {
		t.Fatalf("headers = %v", d.Header)
	}
	_, err = tf.ReadFile(ctx, wsID, taskID, "missing.txt", false)
	wantTaskFileError(t, err, 404, "Sandbox file not found")
	_, err = tf.ReadFile(ctx, wsID, taskID, "gone.txt", false)
	wantTaskFileError(t, err, 410, "Sandbox workspace has expired")
}

func TestTaskSandboxFileList(t *testing.T) {
	m := newFakeManager(t, func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Query().Get("list") {
		case "gone":
			w.WriteHeader(404)
		case "bad":
			_, _ = io.WriteString(w, `{"paths":[1]}`)
		default:
			_, _ = io.WriteString(w, `{"paths":["outputs/a.txt","outputs/b.txt"]}`)
		}
	})
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	ctx := context.Background()
	paths, err := tf.ListFiles(ctx, wsID, taskID, "outputs", false)
	if err != nil || strings.Join(paths, ",") != "outputs/a.txt,outputs/b.txt" {
		t.Fatalf("paths = %v %v", paths, err)
	}
	c := m.last(t)
	if c.path != "/sandbox/files" || c.auth != "Bearer "+fileKey {
		t.Fatalf("call = %+v", c)
	}
	wantQuery(t, c.query, map[string]string{"workspace_id": wsID, "task_id": taskID, "list": "outputs", "ensure": "false"})
	if _, err := tf.ListFiles(ctx, wsID, taskID, "", false); err != nil {
		t.Fatal(err)
	}
	if c := m.last(t); !c.query.Has("list") || c.query.Get("list") != "" {
		t.Fatalf("empty prefix query = %v", c.query)
	}
	_, err = tf.ListFiles(ctx, wsID, taskID, "gone", false)
	wantTaskFileError(t, err, 404, "Sandbox workspace not found")
	_, err = tf.ListFiles(ctx, wsID, taskID, "bad", false)
	wantTaskFileError(t, err, 502, "Sandbox file list is invalid")
}

func TestTaskHarnessFiles(t *testing.T) {
	m := newFakeManager(t, func(http.ResponseWriter, *http.Request) { t.Error("manager called for a harness task") })
	tf, harness := taskFilesOver(t, m.srv.URL, "")
	ctx := context.Background()
	root := "harness-files/" + wsID + "/" + taskID + "/"
	for key, ct := range map[string]string{
		root + "src/b.py":                           "text/x-python",
		root + "src/a.py":                           "",
		root + "page.html":                          "text/html",
		"harness-files/" + wsID + "/other/src/x.py": "",
	} {
		if err := harness.Put(ctx, key, strings.NewReader("data:"+key), -1, blobOpts(ct)); err != nil {
			t.Fatal(err)
		}
	}
	paths, err := tf.ListFiles(ctx, wsID, taskID, "src", true)
	if err != nil || strings.Join(paths, ",") != "src/a.py,src/b.py" {
		t.Fatalf("list src = %v %v", paths, err)
	}
	paths, err = tf.ListFiles(ctx, wsID, taskID, "", true)
	if err != nil || strings.Join(paths, ",") != "page.html,src/a.py,src/b.py" {
		t.Fatalf("list all = %v %v", paths, err)
	}
	if paths, err := tf.ListFiles(ctx, wsID, taskID, "nothing", true); err != nil || paths == nil || len(paths) != 0 {
		t.Fatalf("list none = %#v %v", paths, err)
	}

	d, err := tf.ReadFile(ctx, wsID, taskID, "src/a.py", true)
	if err != nil {
		t.Fatal(err)
	}
	if body := readDownload(t, d); body != "data:"+root+"src/a.py" {
		t.Fatalf("body = %q", body)
	}
	if d.Header.Get("Content-Type") != "application/octet-stream" || d.Header.Get("Content-Length") != itoa(int64(len("data:"+root+"src/a.py"))) ||
		d.Header.Get("Content-Disposition") != `attachment; filename="a.py"; filename*=UTF-8''a.py` || d.Header.Get("X-Content-Type-Options") != "nosniff" {
		t.Fatalf("headers = %v", d.Header)
	}
	d, err = tf.ReadFile(ctx, wsID, taskID, "page.html", true)
	if err != nil {
		t.Fatal(err)
	}
	_ = readDownload(t, d)
	if d.Header.Get("Content-Type") != "text/html; charset=utf-8" {
		t.Fatalf("html headers = %v", d.Header)
	}
	_, err = tf.ReadFile(ctx, wsID, taskID, "src/missing.py", true)
	wantTaskFileError(t, err, 404, "Sandbox file not found")
}

// Python's stream path let a failure reading an error body escape as a 500.
func TestTaskFileErrorBodyCutIsUnavailable(t *testing.T) {
	m := newFakeManager(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Length", "100")
		w.WriteHeader(500)
		_, _ = io.WriteString(w, "par")
		w.(http.Flusher).Flush()
		conn, _, err := w.(http.Hijacker).Hijack()
		if err == nil {
			_ = conn.(*net.TCPConn).SetLinger(0)
			_ = conn.Close()
		}
	})
	tf, _ := taskFilesOver(t, m.srv.URL, fileKey)
	_, err := tf.ReadFile(context.Background(), wsID, taskID, "a.txt", false)
	wantTaskFileError(t, err, 503, "Sandbox file access is temporarily unavailable")
}

func TestTaskFileErrorIs(t *testing.T) {
	err := error(&api.TaskFileError{Status: 404, Detail: "Artifact not found"})
	if !errors.Is(err, &api.TaskFileError{Status: 404, Detail: "Artifact not found"}) || errors.Is(err, api.ErrSandboxExpired) {
		t.Fatal("Is mismatch")
	}
}
