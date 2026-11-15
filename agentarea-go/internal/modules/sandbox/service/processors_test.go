package service

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

const session = "processor-p1"

func (f fixture) outputRef(t *testing.T, path, data string) map[string]any {
	t.Helper()
	ctx := context.Background()
	if _, err := f.svc.TaskWorkspace().PutFiles(ctx, wsID, session, []api.WorkspaceFile{{Path: path, Data: []byte(data)}}, api.WriteOptions{}); err != nil {
		t.Fatal(err)
	}
	key := "workspaces/" + wsID + "/tasks/" + session + "/objects/" + sha(data)
	info, err := f.store.Stat(ctx, key)
	if err != nil {
		t.Fatal(err)
	}
	return map[string]any{"relative_path": path, "object_uri": "s3://artifacts/" + key, "object_version_or_etag": info.ETag, "sha256": sha(data), "size": len(data)}
}

func processorManager(t *testing.T, m *manager, result map[string]any) {
	m.handler = func(w http.ResponseWriter, r *http.Request) bool {
		switch {
		case r.Method == http.MethodPost && r.URL.Path == "/sandbox/executions":
			raw, _ := io.ReadAll(r.Body)
			if c := decodeToken(t, r.Header); c["scope"] != "execution.create" {
				t.Errorf("claims = %v", c)
			}
			_ = json.Unmarshal(raw, &m.created)
			w.WriteHeader(http.StatusAccepted)
			_, _ = io.WriteString(w, `{"id":"ex1","status":"queued","queue_expires_at":"2999-01-01T00:00:00Z"}`)
		case r.Method == http.MethodGet && r.URL.Path == "/sandbox/executions/ex1":
			res, _ := json.Marshal(map[string]any{"id": "ex1", "status": "completed", "result": result})
			_, _ = w.Write(res)
		default:
			return false
		}
		return true
	}
}

func TestProcessorRunReadsStdoutAndStderrOnlyOnFailure(t *testing.T) {
	m := &manager{}
	f, _ := runtimeFixture(t, m)
	out := f.outputRef(t, ".agentarea/executions/e1/stdout.txt", `{"ok":true}`)
	errRef := f.outputRef(t, ".agentarea/executions/e1/stderr.txt", "boom")
	processorManager(t, m, map[string]any{"exit_code": 0, "stdout_ref": out, "stderr_ref": errRef, "stdout_truncated": true})

	run, err := f.svc.Processors().Run(context.Background(), wsID, session, "jq .", 1500*time.Millisecond, 65536)
	if err != nil {
		t.Fatal(err)
	}
	if run != (api.CodeRun{ExitCode: 0, Stdout: `{"ok":true}`, StdoutTruncated: true}) {
		t.Fatalf("run = %+v", run)
	}
	cmd, _ := m.created["command"].(map[string]any)
	if m.created["workspace_id"] != wsID || m.created["task_id"] != session || cmd["command_body"] != "jq ." ||
		cmd["timeout_seconds"] != float64(2) || cmd["stdout_max_bytes"] != float64(65536) || cmd["stderr_max_bytes"] != float64(4096) {
		t.Fatalf("created = %v", m.created)
	}
	if _, has := cmd["workflow_id"]; has {
		t.Fatalf("a processor run names no workflow: %v", cmd)
	}

	processorManager(t, m, map[string]any{"exit_code": 3, "stdout_ref": out, "stderr_ref": errRef})
	run, err = f.svc.Processors().Run(context.Background(), wsID, session, "false", time.Second, 10)
	if err != nil || run.ExitCode != 3 || run.Stderr != "boom" {
		t.Fatalf("failed run = %+v %v", run, err)
	}
}

func TestProcessorRunFailuresAreUnavailable(t *testing.T) {
	m := &manager{handler: func(w http.ResponseWriter, _ *http.Request) bool {
		w.WriteHeader(http.StatusServiceUnavailable)
		return true
	}}
	f, _ := runtimeFixture(t, m)
	if _, err := f.svc.Processors().Run(context.Background(), wsID, session, "ls", time.Second, 10); !errors.Is(err, api.ErrProcessorUnavailable) {
		t.Fatalf("503: %v", err)
	}
	processorManager(t, m, map[string]any{"exit_code": 0, "stdout_ref": map[string]any{"relative_path": "x", "object_uri": "s3://artifacts/nope"}})
	if _, err := f.svc.Processors().Run(context.Background(), wsID, session, "ls", time.Second, 10); !errors.Is(err, api.ErrProcessorUnavailable) {
		t.Fatalf("unreadable output: %v", err)
	}
	bare := newFixture(t, Deps{})
	if _, err := bare.svc.Processors().Run(context.Background(), wsID, session, "ls", time.Second, 10); !errors.Is(err, api.ErrProcessorUnavailable) {
		t.Fatalf("no manager: %v", err)
	}
}
