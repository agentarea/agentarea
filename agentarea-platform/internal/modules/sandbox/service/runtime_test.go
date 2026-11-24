package service

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/api"
)

const (
	taskID  = "task-1"
	control = "0123456789abcdef0123456789abcdef-control"
	fileKey = "file-secret-for-tests"
)

func TestTaskWorkspacePutGetImport(t *testing.T) {
	f := newFixture(t, Deps{})
	ctx := context.Background()
	tw := f.svc.TaskWorkspace()
	ref, err := tw.PutFiles(ctx, wsID, taskID, []api.WorkspaceFile{{Path: "out/a.txt", Data: []byte("A")}}, api.WriteOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if ref.Generation != 1 || !strings.HasPrefix(ref.ManifestURI, "s3://artifacts/workspaces/"+wsID+"/tasks/"+taskID+"/") {
		t.Fatalf("ref = %+v", ref)
	}
	data, ct, err := tw.Get(ctx, wsID, taskID, "out/a.txt")
	if err != nil || string(data) != "A" || ct != "text/plain" {
		t.Fatalf("get = %q %q %v", data, ct, err)
	}
	if ok, err := tw.Exists(ctx, wsID, taskID, "out/missing"); ok || err != nil {
		t.Fatalf("exists missing = %v %v", ok, err)
	}
	if d, err := tw.Digest(ctx, wsID, taskID, "out/a.txt"); err != nil || d != "559aead08264d5795d3909718cdd05abd49572e84fe55590eef31a88a08fdffd" {
		t.Fatalf("digest = %q %v", d, err)
	}
	if _, err := tw.Digest(ctx, wsID, taskID, "out/missing"); !errors.Is(err, api.ErrFileNotFound) {
		t.Fatalf("digest of a missing file = %v", err)
	}
	f.put(t, "projects/p1/in.csv", "1,2")
	f.put(t, "projects/p1/sub/x.txt", "x")
	ref2, err := tw.ImportPrefix(ctx, wsID, taskID, "projects/p1", "inputs/project", api.WriteOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if ref2.Generation != 2 || ref2.BaseGeneration != 1 {
		t.Fatalf("ref2 = %+v", ref2)
	}
	if data, _, err := tw.Get(ctx, wsID, taskID, "inputs/project/sub/x.txt"); err != nil || string(data) != "x" {
		t.Fatalf("imported = %q %v", data, err)
	}
	if _, err := tw.PutFiles(ctx, wsID, taskID, []api.WorkspaceFile{{Path: "../x", Data: []byte("x")}}, api.WriteOptions{}); !errors.Is(err, api.ErrWorkspaceInvalid) {
		t.Fatalf("traversal err = %v", err)
	}
	if _, _, err := tw.Get(ctx, wsID, "../t", "a"); !errors.Is(err, api.ErrWorkspaceInvalid) {
		t.Fatalf("bad task err = %v", err)
	}
	v, err := f.svc.Download(ctx, f.ws, "tasks/"+taskID+"/workspace/out/a.txt")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(v.Body)
	_ = v.Body.Close()
	if string(body) != "A" {
		t.Fatalf("download = %q", body)
	}
}

func decodeToken(t *testing.T, h http.Header) map[string]any {
	t.Helper()
	tok := strings.TrimPrefix(h.Get("Authorization"), "Bearer ")
	payload, sig, ok := strings.Cut(tok, ".")
	if !ok {
		t.Fatalf("token = %q", tok)
	}
	mac := hmac.New(sha256.New, []byte(control))
	mac.Write([]byte(payload))
	if base64.RawURLEncoding.EncodeToString(mac.Sum(nil)) != sig {
		t.Fatal("bad signature")
	}
	raw, err := base64.RawURLEncoding.DecodeString(payload)
	if err != nil {
		t.Fatal(err)
	}
	var claims map[string]any
	if err := json.Unmarshal(raw, &claims); err != nil {
		t.Fatal(err)
	}
	return claims
}

func TestSignerTokenShape(t *testing.T) {
	now := func() time.Time { return time.Unix(1000, 0) }
	s, err := newSigner(control, wsID, taskID, now)
	if err != nil {
		t.Fatal(err)
	}
	h, err := s.headers("execution.read", "ex1", nil)
	if err != nil {
		t.Fatal(err)
	}
	c := decodeToken(t, h)
	if c["scope"] != "execution.read" || c["execution_id"] != "ex1" || c["expires_at"] != float64(1300) || c["v"] != float64(1) {
		t.Fatalf("claims = %v", c)
	}
	if h.Get("X-Agentarea-Workspace-ID") != wsID || h.Get("X-Agentarea-Task-ID") != taskID {
		t.Fatalf("headers = %v", h)
	}
	if _, err := newSigner("short", wsID, taskID, now); err == nil {
		t.Fatal("short secret accepted")
	}
	if _, err := s.headers("execution.create", "ex1", nil); err == nil {
		t.Fatal("create bound an execution id")
	}
}

// manager is a fake sandbox manager for the shell, barrier and inventory.
type manager struct {
	mu        sync.Mutex
	polls     int
	cancelled bool
	created   map[string]any
	handler   func(w http.ResponseWriter, r *http.Request) bool
}

func (m *manager) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.handler != nil && m.handler(w, r) {
		return
	}
	http.NotFound(w, r)
}

func runtimeFixture(t *testing.T, m *manager) (fixture, *httptest.Server) {
	t.Helper()
	srv := httptest.NewServer(m)
	t.Cleanup(srv.Close)
	f := newFixture(t, Deps{Manager: Manager{URL: srv.URL, InspectSecret: "inspect", FileSecret: fileKey, ControlSecret: control}, PollInterval: time.Millisecond})
	return f, srv
}

func TestBashRunsAndReadsOutputByReference(t *testing.T) {
	m := &manager{}
	f, _ := runtimeFixture(t, m)
	ctx := context.Background()
	ref, err := f.svc.TaskWorkspace().PutFiles(ctx, wsID, taskID, []api.WorkspaceFile{{Path: ".agentarea/executions/e1/stdout.txt", Data: []byte("hi\n")}}, api.WriteOptions{})
	if err != nil || ref.Generation != 1 {
		t.Fatal(err)
	}
	key := "workspaces/" + wsID + "/tasks/" + taskID + "/objects/" + sha("hi\n")
	info, err := f.store.Stat(ctx, key)
	if err != nil {
		t.Fatal(err)
	}
	stdoutRef := map[string]any{"relative_path": ".agentarea/executions/e1/stdout.txt", "object_uri": "s3://artifacts/" + key, "object_version_or_etag": info.ETag, "sha256": sha("hi\n"), "size": 3}
	empty := "workspaces/" + wsID + "/tasks/" + taskID + "/objects/" + sha("")
	if _, err := f.svc.TaskWorkspace().PutFiles(ctx, wsID, taskID, []api.WorkspaceFile{{Path: ".agentarea/executions/e1/stderr.txt", Data: nil}}, api.WriteOptions{}); err != nil {
		t.Fatal(err)
	}
	einfo, _ := f.store.Stat(ctx, empty)
	stderrRef := map[string]any{"relative_path": ".agentarea/executions/e1/stderr.txt", "object_uri": "s3://artifacts/" + empty, "object_version_or_etag": einfo.ETag, "sha256": sha(""), "size": 0}
	m.handler = func(w http.ResponseWriter, r *http.Request) bool {
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/sandbox/executions":
			raw, _ := io.ReadAll(r.Body)
			c := decodeToken(t, r.Header)
			sum := sha256.Sum256(raw)
			if c["body_sha256"] != hexOf(sum[:]) || c["scope"] != "execution.create" {
				t.Errorf("claims = %v", c)
			}
			_ = json.Unmarshal(raw, &m.created)
			w.WriteHeader(http.StatusAccepted)
			_, _ = io.WriteString(w, `{"id":"ex1","status":"queued","queue_expires_at":"2999-01-01T00:00:00Z"}`)
		case r.Method == http.MethodGet && r.URL.Path == "/sandbox/executions/ex1":
			m.polls++
			if m.polls < 2 {
				_, _ = io.WriteString(w, `{"id":"ex1","status":"running","execution_expires_at":"2999-01-01T00:00:00Z"}`)
				return true
			}
			res, _ := json.Marshal(map[string]any{"id": "ex1", "status": "completed", "result": map[string]any{"exit_code": 0, "stdout_ref": stdoutRef, "stderr_ref": stderrRef}})
			_, _ = w.Write(res)
		default:
			return false
		}
		return true
	}
	timeout := 30
	out, err := f.svc.Runtime().Bash(ctx, api.BashCall{WorkspaceID: wsID, TaskID: taskID, WorkflowID: "wf", Command: "echo hi", TimeoutSeconds: &timeout})
	if err != nil {
		t.Fatal(err)
	}
	if !out.Success || out.Result != "hi" || out.Outcome != "exit" || *out.ExitCode != 0 {
		t.Fatalf("outcome = %+v", out)
	}
	cmd, _ := m.created["command"].(map[string]any)
	if m.created["workspace_id"] != wsID || cmd["command_body"] != "echo hi" || cmd["timeout_seconds"] != float64(30) || cmd["workflow_id"] != "wf" {
		t.Fatalf("created = %v", m.created)
	}
}

func hexOf(b []byte) string {
	const digits = "0123456789abcdef"
	out := make([]byte, 0, len(b)*2)
	for _, c := range b {
		out = append(out, digits[c>>4], digits[c&15])
	}
	return string(out)
}

func TestBashFailuresAreToolErrors(t *testing.T) {
	m := &manager{handler: func(w http.ResponseWriter, r *http.Request) bool {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = io.WriteString(w, `{"error":"sandbox_control_unavailable"}`)
		return true
	}}
	f, _ := runtimeFixture(t, m)
	out, err := f.svc.Runtime().Bash(context.Background(), api.BashCall{WorkspaceID: wsID, TaskID: taskID, Command: "ls"})
	if err != nil || out.Success || out.Outcome != "error" || !strings.HasPrefix(out.Error, "sandbox returned HTTP 503") {
		t.Fatalf("outcome = %+v, %v", out, err)
	}
	out, _ = f.svc.Runtime().Bash(context.Background(), api.BashCall{WorkspaceID: wsID, TaskID: taskID, Command: "  "})
	if out.Error != "command must be a non-empty string" || out.Result != "Error: command must be a non-empty string" {
		t.Fatalf("outcome = %+v", out)
	}
}

func TestBashCancelsAbandonedExecution(t *testing.T) {
	m := &manager{}
	m.handler = func(w http.ResponseWriter, r *http.Request) bool {
		switch r.Method {
		case http.MethodPost:
			w.WriteHeader(http.StatusAccepted)
			_, _ = io.WriteString(w, `{"id":"ex2","status":"running","execution_expires_at":"2999-01-01T00:00:00Z"}`)
		case http.MethodGet:
			_, _ = io.WriteString(w, `{"id":"ex2","status":"running","execution_expires_at":"2999-01-01T00:00:00Z"}`)
		case http.MethodDelete:
			m.cancelled = true
			_, _ = io.WriteString(w, `{"id":"ex2","status":"cancelled"}`)
		}
		return true
	}
	f, _ := runtimeFixture(t, m)
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Millisecond)
	defer cancel()
	if _, err := f.svc.Runtime().Bash(ctx, api.BashCall{WorkspaceID: wsID, TaskID: taskID, Command: "sleep 9"}); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v", err)
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.cancelled {
		t.Fatal("execution not cancelled")
	}
}

func TestValidateArtifacts(t *testing.T) {
	m := &manager{handler: func(w http.ResponseWriter, r *http.Request) bool {
		if r.Header.Get("Authorization") != "Bearer "+fileKey {
			w.WriteHeader(http.StatusUnauthorized)
			return true
		}
		switch r.URL.Path {
		case "/sandbox/files":
			if r.URL.Query().Get("ensure") != "false" || r.URL.Query().Get("list") != "outputs" {
				w.WriteHeader(http.StatusBadRequest)
				return true
			}
			_, _ = io.WriteString(w, `{"paths":["outputs/r.md","notes.txt"]}`)
		case "/sandbox/artifacts":
			var body map[string]string
			_ = json.NewDecoder(r.Body).Decode(&body)
			switch body["path"] {
			case "missing.txt":
				w.WriteHeader(http.StatusNotFound)
			default:
				w.WriteHeader(http.StatusCreated)
				_, _ = io.WriteString(w, `{"sha256":"`+sha(body["path"])+`","size":4}`)
			}
		default:
			return false
		}
		return true
	}}
	f, _ := runtimeFixture(t, m)
	ctx := context.Background()
	v, err := f.svc.Runtime().ValidateArtifacts(ctx, wsID, taskID, []string{"/workspace/report.pdf", "./report.pdf", "missing.txt"})
	if err != nil {
		t.Fatal(err)
	}
	if v.State != "failed" || len(v.Evidence) != 2 || v.Evidence[0].Path != "report.pdf" || v.Evidence[1].Path != "outputs/r.md" {
		t.Fatalf("validation = %+v", v)
	}
	if len(v.Issues) != 1 || v.Issues[0].Code != "artifact_missing" {
		t.Fatalf("issues = %+v", v.Issues)
	}
	v, _ = f.svc.Runtime().ValidateArtifacts(ctx, wsID, taskID, []string{"../etc/passwd"})
	if v.State != "failed" || v.Issues[0].Code != "invalid_artifact_path" {
		t.Fatalf("traversal = %+v", v)
	}
	g := newFixture(t, Deps{})
	v, _ = g.svc.Runtime().ValidateArtifacts(ctx, wsID, taskID, nil)
	if v.State != "passed" {
		t.Fatalf("unconfigured empty = %+v", v)
	}
	v, _ = g.svc.Runtime().ValidateArtifacts(ctx, wsID, taskID, []string{"a"})
	if v.State != "unavailable" || v.Capability != "published_artifact_store" {
		t.Fatalf("unconfigured = %+v", v)
	}
}

func TestSandboxesInventory(t *testing.T) {
	body := `{"items":[{"id":"s1","provider":"k8s","workspace_id":"` + wsID + `","task_id":"t","state":"ready","created_at":"2026-11-12T10:00:00+00:00","expires_at":null,"resources":{"cpu":"1","memory":"1Gi"},"isolation":"gvisor"}],"total":1}`
	m := &manager{handler: func(w http.ResponseWriter, r *http.Request) bool {
		if r.URL.Path != "/sandbox/sessions" || r.Header.Get("Authorization") != "Bearer inspect" || r.URL.Query().Get("workspace_id") != wsID {
			w.WriteHeader(http.StatusUnauthorized)
			return true
		}
		_, _ = io.WriteString(w, body)
		return true
	}}
	f, _ := runtimeFixture(t, m)
	ctx := context.Background()
	l, err := f.svc.Sandboxes(ctx, wsID)
	if err != nil || l.Total != 1 || l.Items[0].CreatedAt != "2026-11-12T10:00:00Z" || l.Items[0].ExpiresAt != nil || l.Items[0].Memory != "1Gi" {
		t.Fatalf("list = %+v, %v", l, err)
	}
	for _, bad := range []string{
		strings.Replace(body, wsID, "other", 1),
		strings.Replace(body, `"isolation"`, `"extra":1,"isolation"`, 1),
		strings.Replace(body, `"id":"s1"`, `"id":1`, 1),
		`[]`,
	} {
		body = bad
		if _, err := f.svc.Sandboxes(ctx, wsID); httpStatus(t, err) != http.StatusBadGateway {
			t.Fatalf("%s: %v", bad, err)
		}
	}
	if _, err := f.svc.Sandboxes(ctx, "other-ws"); httpStatus(t, err) != http.StatusServiceUnavailable {
		t.Fatal(err)
	}
	g := newFixture(t, Deps{})
	if _, err := g.svc.Sandboxes(ctx, wsID); httpStatus(t, err) != http.StatusServiceUnavailable {
		t.Fatal(err)
	}
}

func TestRuntimeManifest(t *testing.T) {
	good := map[string]any{
		"schema_version": 2, "image_version": "1", "managed_environment": "immutable",
		"python": map[string]any{"version": "3.12", "executable": "/usr/bin/python3"}, "node": map[string]any{"version": "22", "npm_version": nil},
		"features":             map[string]any{"browser": "none", "managed_environment_mutation": false, "arbitrary_workspace_code": true},
		"execution_supervisor": map[string]any{"path": "/opt/sup", "sha256": sha("s"), "protocol_version": 1, "command_uid": 1000, "command_gid": 1000},
	}
	var payload []byte
	m := &manager{handler: func(w http.ResponseWriter, r *http.Request) bool {
		_, _ = w.Write(payload)
		return true
	}}
	f, _ := runtimeFixture(t, m)
	payload, _ = json.Marshal(good)
	man, err := f.svc.Runtime().Manifest(context.Background())
	if err != nil || man.ExecutionSupervisor.CommandUID != 1000 || man.Tools == nil {
		t.Fatalf("manifest = %+v, %v", man, err)
	}
	good["managed_environment"] = "mutable"
	payload, _ = json.Marshal(good)
	if _, err := f.svc.Runtime().Manifest(context.Background()); !errors.Is(err, api.ErrRuntimeUnavailable) {
		t.Fatalf("err = %v", err)
	}
}

func TestValidateSecretsRefusesPublished(t *testing.T) {
	if err := ValidateSecrets(Manager{FileSecret: "fresh"}); err != nil {
		t.Fatal(err)
	}
	if err := ValidateSecrets(Manager{ControlSecret: "agentarea-dev-sandbox-control-secret-change-me"}); err == nil {
		t.Fatal("published control secret accepted")
	}
}
