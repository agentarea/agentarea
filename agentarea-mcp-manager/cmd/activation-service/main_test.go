package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
)

func init() {
	logger = slog.New(slog.NewJSONHandler(os.Stdout, nil))
}

func decodeExecResp(t *testing.T, w *httptest.ResponseRecorder) ExecuteResponse {
	t.Helper()
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp ExecuteResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return resp
}

func postExecute(t *testing.T, req ExecuteRequest, commandContent string) ExecuteResponse {
	t.Helper()
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	if req.PackageInstall == "" {
		req.PackageInstall = runtimeinfo.PackageInstallAllowed
	}
	runtimePath := filepath.Join(t.TempDir(), "runtime.json")
	runtimeJSON := `{
  "schema_version": 1,
  "image_version": "test-runtime",
  "managed_environment": "mutable",
  "python": {"version": "3.12.0", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "22.0.0", "npm_version": "10.0.0"},
  "tools": {},
  "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true}
}`
	if err := os.WriteFile(runtimePath, []byte(runtimeJSON), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("RUNTIME_MANIFEST_PATH", runtimePath)
	if req.TaskID == "" {
		req.TaskID = req.WorkflowID
	}
	if req.TaskID == "" {
		req.TaskID = "task-test"
	}
	if req.WorkspaceID == "" {
		req.WorkspaceID = "workspace-test"
	}
	if req.CommandBody == "" {
		req.CommandBody = commandContent
	}
	body, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	r := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewReader(body))
	token, err := activationauth.SignFromEnv(activationauth.ScopeExecute, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
		Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body), time.Now())
	if err != nil {
		t.Fatalf("sign request: %v", err)
	}
	r.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	executeHandler(w, r)
	return decodeExecResp(t, w)
}

func TestExecuteHandlerSessionWorkspacePersistsAcrossCalls(t *testing.T) {
	workspaceRoot = t.TempDir()
	resp1 := postExecute(t, ExecuteRequest{TaskID: "task-session"}, "echo persisted > marker.txt && pwd")
	if resp1.ExitCode != 0 {
		t.Fatalf("call 1 exit %d, stderr=%q", resp1.ExitCode, resp1.Stderr)
	}

	resp2 := postExecute(t, ExecuteRequest{TaskID: "task-session"}, "cat marker.txt 2>&1; true")
	// Session semantics: files a previous call wrote survive for the task; only
	// manifest inputs are re-synced (by per-file replace), the workspace is not wiped.
	if !strings.Contains(resp2.Stdout, "persisted") {
		t.Fatalf("session workspace state did not persist across calls: %q", resp2.Stdout)
	}
}

func TestExecuteHandlerDifferentTasksAreIsolated(t *testing.T) {
	workspaceRoot = t.TempDir()

	resp1 := postExecute(t, ExecuteRequest{TaskID: "task-A"}, "echo from-A > marker.txt")
	if resp1.ExitCode != 0 {
		t.Fatalf("workflow-A write failed: %s", resp1.Stderr)
	}

	resp2 := postExecute(t, ExecuteRequest{TaskID: "task-B"}, "cat marker.txt 2>&1; true")
	if strings.Contains(resp2.Stdout, "from-A") {
		t.Fatalf("workflow-B saw workflow-A's file: %q", resp2.Stdout)
	}
}

func TestExecuteHandlerRejectsBadTaskID(t *testing.T) {
	cases := []string{
		"../escape",
		"a/b",
		"id with space",
		"id;rm -rf",
	}
	for _, id := range cases {
		t.Run(id, func(t *testing.T) {
			body, _ := json.Marshal(ExecuteRequest{
				CommandPath: ".agentarea/commands/command.sh",
				TaskID:      id,
			})
			r := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewReader(body))
			w := httptest.NewRecorder()
			executeHandler(w, r)
			if w.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for task_id=%q, got %d body=%s", id, w.Code, w.Body.String())
			}
		})
	}
}

func TestExecuteHandlerExecutesHydratedCommandPath(t *testing.T) {
	workspaceRoot = t.TempDir()

	resp := postExecute(t, ExecuteRequest{TaskID: "test-command-path"}, "echo $((2 + 2))")
	if resp.ExitCode != 0 {
		t.Fatalf("exit %d, stderr=%q", resp.ExitCode, resp.Stderr)
	}
	if !strings.Contains(resp.Stdout, "4") {
		t.Fatalf("expected '4' in stdout, got %q", resp.Stdout)
	}
}

func TestExecuteHandlerBoundsEachOutputStreamAndReportsTruncation(t *testing.T) {
	workspaceRoot = t.TempDir()
	resp := postExecute(t, ExecuteRequest{TaskID: "test-output-bounds", StdoutMaxBytes: 4, StderrMaxBytes: 3}, "printf abcdef; printf vwxyz >&2")
	if resp.Stdout != "abcd" || !resp.StdoutTruncated {
		t.Fatalf("stdout = %q, truncated = %v", resp.Stdout, resp.StdoutTruncated)
	}
	if resp.Stderr != "vwx" || !resp.StderrTruncated {
		t.Fatalf("stderr = %q, truncated = %v", resp.Stderr, resp.StderrTruncated)
	}
}

func TestExecuteHandlerRejectsMissingBearerBeforeExecution(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	body, _ := json.Marshal(ExecuteRequest{
		CommandBody: "echo ok", WorkspaceID: "workspace-test", TaskID: "task-test",
	})
	req := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewReader(body))
	response := httptest.NewRecorder()

	executeHandler(response, req)

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized response = %d %s", response.Code, response.Body.String())
	}
}

func TestExecuteHandlerRejectsBearerReplayedWithAlteredBody(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	original := ExecuteRequest{
		CommandBody: "echo original", WorkspaceID: "workspace-test", TaskID: "task-test",
	}
	originalBody, err := json.Marshal(original)
	if err != nil {
		t.Fatal(err)
	}
	token, err := activationauth.SignFromEnv(activationauth.ScopeExecute, activationauth.Identity{
		WorkspaceID: "workspace-test", TaskID: "task-test", Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(originalBody), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	altered := original
	altered.CommandBody = "echo altered"
	alteredBody, err := json.Marshal(altered)
	if err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewReader(alteredBody))
	req.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()

	executeHandler(response, req)

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("altered-body response = %d %s", response.Code, response.Body.String())
	}
}

func TestDecodeExecuteRequestRejectsAllLegacyInlineFileShapes(t *testing.T) {
	for _, payload := range []string{
		`{"script_name":"cmd.sh","script_content":"true"}`,
		`{"script_name":"cmd.sh","script_content":"true","input_files":[]}`,
		`{"script_name":"cmd.sh","script_content":"true","content_base64":"ZmlsZQ=="}`,
		`{"command_path":".agentarea/commands/command.sh","args":["REDIS-ARGS-CANARY"]}`,
		`{"command_path":".agentarea/commands/command.sh","env":{"CANARY":"REDIS-ENV-CANARY"}}`,
		`{"command_path":".agentarea/commands/command.sh","script":"REDIS-SCRIPT-CANARY"}`,
	} {
		if _, err := decodeExecuteRequest(strings.NewReader(payload)); err == nil || !strings.Contains(err.Error(), "unsupported_contract_version") {
			t.Fatalf("legacy payload accepted: %s; error = %v", payload, err)
		}
	}
}

func TestSandboxExecutionEnvironmentDerivesTaskWorkspaceValues(t *testing.T) {
	t.Setenv("AGENTAREA_WORKSPACE_ID", "caller-workspace-canary")
	t.Setenv("AGENTAREA_TASK_ID", "caller-task-canary")
	t.Setenv("AGENTAREA_WORKSPACE_ROOT", "caller-root-canary")
	t.Setenv("AGENTAREA_INPUT_DIR", "caller-input-canary")

	joined := strings.Join(sandboxExecutionEnvironment("workspace-1", "task-1", "/workspace/tasks/task-1"), "\n")
	for _, expected := range []string{
		"AGENTAREA_WORKSPACE_ID=workspace-1",
		"AGENTAREA_TASK_ID=task-1",
		"AGENTAREA_WORKSPACE_ROOT=/workspace/tasks/task-1",
		"AGENTAREA_INPUT_DIR=inputs",
	} {
		if !strings.Contains(joined, expected) {
			t.Fatalf("derived execution environment lacks %q: %s", expected, joined)
		}
	}
	for _, forbidden := range []string{"caller-workspace-canary", "caller-task-canary", "caller-root-canary", "caller-input-canary"} {
		if strings.Contains(joined, forbidden) {
			t.Fatalf("execution environment retained caller value %q", forbidden)
		}
	}
}

func TestResolveExecutionWorkspaceMakesRootTraversableAndTaskPrivate(t *testing.T) {
	originalRoot := workspaceRoot
	workspaceRoot = t.TempDir()
	t.Cleanup(func() { workspaceRoot = originalRoot })

	dir, err := resolveExecutionWorkspace("task-permissions")
	if err != nil {
		t.Fatal(err)
	}
	tasksInfo, err := os.Stat(filepath.Join(workspaceRoot, "tasks"))
	if err != nil {
		t.Fatal(err)
	}
	if got := tasksInfo.Mode().Perm(); got != 0o711 {
		t.Fatalf("tasks root permissions = %04o, want 0711", got)
	}
	taskInfo, err := os.Stat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if got := taskInfo.Mode().Perm(); got != 0o700 {
		t.Fatalf("task permissions = %04o, want 0700", got)
	}
}

func TestDiscoverAutoArtifactsDoesNotSilentlyTruncate(t *testing.T) {
	dir := t.TempDir()
	want := make([]string, 0, 25)
	for index := 0; index < 25; index++ {
		name := filepath.ToSlash(filepath.Join("reports", fmt.Sprintf("result-%02d.txt", index)))
		if err := os.MkdirAll(filepath.Dir(filepath.Join(dir, name)), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, name), []byte("result"), 0o600); err != nil {
			t.Fatal(err)
		}
		want = append(want, name)
	}
	got := discoverAutoArtifacts(dir, time.Time{})
	sort.Strings(got)
	sort.Strings(want)
	if len(got) != len(want) || strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Fatalf("discovered artifacts = %v, want %v", got, want)
	}
}

func TestSandboxProcessEnvironmentRemovesStorageCredentials(t *testing.T) {
	t.Setenv("AWS_ACCESS_KEY_ID", "canary-access-key")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "canary-secret-key")
	t.Setenv("AWS_SESSION_TOKEN", "canary-session-token")
	t.Setenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", "canary-credential-endpoint")
	t.Setenv("RUSTFS_SECRET_KEY", "canary-rustfs-secret")
	t.Setenv("SANDBOX_WORKSPACE_S3_CREDENTIAL_TOKEN", "canary-workspace-token")
	t.Setenv(activationauth.SecretEnv, "canary-activation-auth-secret")
	t.Setenv("WORKSPACE_NON_SECRET_CANARY", "preserved")

	joined := strings.Join(sandboxProcessEnvironment(), "\n")
	for _, forbidden := range []string{"canary-access-key", "canary-secret-key", "canary-session-token", "canary-credential-endpoint", "canary-rustfs-secret", "canary-workspace-token", "canary-activation-auth-secret"} {
		if strings.Contains(joined, forbidden) {
			t.Fatalf("sandbox environment contains storage credential %q", forbidden)
		}
	}
	if !strings.Contains(joined, "WORKSPACE_NON_SECRET_CANARY=preserved") {
		t.Fatal("sandbox environment removed a non-secret variable")
	}
}

func TestRuntimeManifestHandlerServesValidatedManifest(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	payload := `{
  "schema_version": 1,
  "image_version": "test-runtime",
  "managed_environment": "mutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {"git": "git version 2.0", "jq": "jq-1.7", "curl": "curl 8.0"},
  "packages": {"openpyxl": "3.1.5"},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true}
}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("RUNTIME_MANIFEST_PATH", path)

	req := httptest.NewRequest(http.MethodGet, "/runtime/manifest", nil)
	response := httptest.NewRecorder()
	runtimeManifestHandler(response, req)
	if response.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", response.Code, response.Body.String())
	}
	var got map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["managed_environment"] != "mutable" {
		t.Fatalf("unexpected manifest: %v", got)
	}
}

func TestRuntimeManifestHandlerFailsClosedForInvalidManifest(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	if err := os.WriteFile(path, []byte(`{"schema_version":1}`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("RUNTIME_MANIFEST_PATH", path)

	req := httptest.NewRequest(http.MethodGet, "/runtime/manifest", nil)
	response := httptest.NewRecorder()
	runtimeManifestHandler(response, req)
	if response.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d: %s", response.Code, response.Body.String())
	}
}

func TestRuntimeManifestHandlerRejectsInvalidProfile(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/runtime/manifest?package_install=untrusted", nil)
	response := httptest.NewRecorder()
	runtimeManifestHandler(response, req)
	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d: %s", response.Code, response.Body.String())
	}
}

func TestRuntimeManifestHandlerRejectsManifestFromDifferentProfile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "runtime.json")
	payload := `{
  "schema_version": 1,
  "image_version": "test-runtime",
  "managed_environment": "mutable",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {}, "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true}
}`
	if err := os.WriteFile(path, []byte(payload), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("RUNTIME_MANIFEST_PATH", path)

	req := httptest.NewRequest(http.MethodGet, "/runtime/manifest?package_install=locked", nil)
	response := httptest.NewRecorder()
	runtimeManifestHandler(response, req)
	if response.Code != http.StatusConflict {
		t.Fatalf("expected 409, got %d: %s", response.Code, response.Body.String())
	}
}

func TestObjectStoreEndpointHost(t *testing.T) {
	t.Run("fails hard when unset", func(t *testing.T) {
		t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", "")
		t.Setenv("AWS_ENDPOINT_URL", "")
		if _, err := objectStoreEndpointHost(); err == nil {
			t.Fatal("expected an error when no object store endpoint is configured")
		}
	})
	t.Run("primary variable wins and trailing slash is trimmed", func(t *testing.T) {
		t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", "http://rustfs:9000/")
		t.Setenv("AWS_ENDPOINT_URL", "https://s3.amazonaws.com")
		host, err := objectStoreEndpointHost()
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if host != "rustfs:9000" {
			t.Fatalf("host = %q, want rustfs:9000", host)
		}
	})
	t.Run("falls back to AWS_ENDPOINT_URL", func(t *testing.T) {
		t.Setenv("SANDBOX_WORKSPACE_S3_ENDPOINT", "")
		t.Setenv("AWS_ENDPOINT_URL", "https://s3.amazonaws.com")
		host, err := objectStoreEndpointHost()
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if host != "s3.amazonaws.com" {
			t.Fatalf("host = %q, want s3.amazonaws.com", host)
		}
	})
}

func TestCheckedIntFromUint32(t *testing.T) {
	for _, value := range []uint32{0, 1000, math.MaxInt32} {
		got, err := checkedIntFromUint32(value)
		if err != nil {
			t.Fatalf("checkedIntFromUint32(%d) errored: %v", value, err)
		}
		if got != int(value) {
			t.Fatalf("checkedIntFromUint32(%d) = %d, want %d", value, got, int(value))
		}
	}
	if _, err := checkedIntFromUint32(math.MaxInt32 + 1); err == nil {
		t.Fatal("expected an error for a uid/gid above the 32-bit signed int range")
	}
}
