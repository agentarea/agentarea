package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestPrepareTaskWorkspaceDoesNotFollowAgentSymlinks(t *testing.T) {
	workspace := t.TempDir()
	if err := os.Symlink(filepath.Join(t.TempDir(), "missing-target"), filepath.Join(workspace, "agent-link")); err != nil {
		t.Fatal(err)
	}
	credential := &syscall.Credential{Uid: uint32(os.Getuid()), Gid: uint32(os.Getgid())}
	if err := prepareTaskWorkspace(workspace, credential); err != nil {
		t.Fatalf("prepareTaskWorkspace followed an agent-controlled symlink: %v", err)
	}
}

func TestLoadActivationPolicyRejectsMissingOrMalformedValues(t *testing.T) {
	t.Setenv("MAX_EXECUTION_TIMEOUT_SECONDS", "1800")
	t.Setenv("SANDBOX_WORKSPACE_MAX_FILES", "10000")
	t.Setenv("SANDBOX_WORKSPACE_MAX_FILE_BYTES", "268435456")
	t.Setenv("SANDBOX_WORKSPACE_MAX_BYTES", "2147483648")
	t.Setenv("IDLE_TIMEOUT_SECONDS", "not-a-number")
	if _, err := loadActivationPolicy(); err == nil {
		t.Fatal("malformed idle timeout unexpectedly disabled the watchdog")
	}
	t.Setenv("IDLE_TIMEOUT_SECONDS", "0")
	policy, err := loadActivationPolicy()
	if err != nil {
		t.Fatal(err)
	}
	if policy.MaxExecutionTimeoutSeconds != 1800 || policy.WorkspaceLimits != (sandboxruntime.WorkspaceLimits{
		MaxFiles: 10000, MaxFileBytes: 268435456, MaxBytes: 2147483648,
	}) || policy.IdleTimeout != 0 {
		t.Fatalf("policy = %+v", policy)
	}
}

func TestWorkspaceEntryLimitCountsFilesDirectoriesAndSymlinks(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "one"), []byte("1"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(dir, "directory"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("one", filepath.Join(dir, "link")); err != nil {
		t.Fatal(err)
	}
	limits := sandboxruntime.WorkspaceLimits{MaxFiles: 2, MaxFileBytes: 10, MaxBytes: 20}
	if err := enforceWorkspaceLimits(dir, limits); !errors.Is(err, errWorkspaceQuotaExceeded) {
		t.Fatalf("live workspace entry overflow error = %v", err)
	}
}

func init() {
	logger = slog.New(slog.NewJSONHandler(os.Stdout, nil))
	servicePolicy = activationPolicy{
		MaxExecutionTimeoutSeconds: 30,
		WorkspaceLimits: sandboxruntime.WorkspaceLimits{
			MaxFiles: 10_000, MaxFileBytes: 256 * 1024 * 1024, MaxBytes: 2 * 1024 * 1024 * 1024,
		},
	}
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
	return decodeExecResp(t, postExecuteRequest(t, req, commandContent))
}

func postExecuteRequest(t *testing.T, req ExecuteRequest, commandContent string) *httptest.ResponseRecorder {
	return postExecuteRequestWithHooks(t, req, commandContent, runTestSandboxCommand, func() {})
}

func postExecuteRequestWithHooks(
	t *testing.T,
	req ExecuteRequest,
	commandContent string,
	runner supervisedCommandRunner,
	invalidator func(),
) *httptest.ResponseRecorder {
	t.Helper()
	originalRunner := runSandboxCommand
	originalInvalidator := executorInvalidator
	runSandboxCommand = runner
	executorInvalidator = invalidator
	t.Cleanup(func() {
		runSandboxCommand = originalRunner
		executorInvalidator = originalInvalidator
	})
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	if req.TimeoutSeconds == 0 {
		req.TimeoutSeconds = 5
	}
	runtimePath := filepath.Join(t.TempDir(), "runtime.json")
	runtimeJSON := `{
  "schema_version": 2,
  "managed_environment": "mutable",
  "image_version": "test-runtime",
  "python": {"version": "3.12.0", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "22.0.0", "npm_version": "10.0.0"},
  "tools": {},
  "packages": {},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true},
  "execution_supervisor": {"path":"/usr/local/bin/agentarea-exec-supervisor","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","protocol_version":1,"command_uid":10001,"command_gid":10001}
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
	return w
}

func TestExecuteHandlerRejectsTimeoutAboveSharedPolicyBeforeExecution(t *testing.T) {
	originalPolicy := servicePolicy
	servicePolicy.MaxExecutionTimeoutSeconds = 17
	t.Cleanup(func() { servicePolicy = originalPolicy })

	var executed bool
	response := postExecuteRequestWithHooks(t, ExecuteRequest{
		WorkspaceID: "workspace-timeout", TaskID: "task-timeout",
		TimeoutSeconds: 18,
	}, "true", func(context.Context, supervisedCommandRequest) (execsupervisor.Status, error) {
		executed = true
		return execsupervisor.Status{}, nil
	}, func() {})

	if response.Code != http.StatusBadRequest || !strings.Contains(response.Body.String(), "between 1 and 17") {
		t.Fatalf("response = %d %s, want explicit configured timeout rejection", response.Code, response.Body.String())
	}
	if executed {
		t.Fatal("over-policy command reached the execution runtime")
	}
}

func runTestSandboxCommand(ctx context.Context, request supervisedCommandRequest) (execsupervisor.Status, error) {
	timeoutCtx, cancel := context.WithTimeout(ctx, time.Duration(request.TimeoutSeconds)*time.Second)
	defer cancel()
	command := exec.CommandContext(timeoutCtx, "/bin/sh", request.CommandPath)
	command.Dir = request.WorkspaceDir
	command.Env = request.Environment
	command.Stdout = request.Stdout
	command.Stderr = request.Stderr
	err := command.Run()
	if errors.Is(timeoutCtx.Err(), context.DeadlineExceeded) {
		return execsupervisor.Status{
			ProtocolVersion: execsupervisor.ProtocolVersion, SupervisorSHA256: request.Attestation.SHA256,
			Quiescent: true, ChildExitCode: 124, TimedOut: true,
		}, nil
	}
	exitCode := 0
	if err != nil {
		var exitErr *exec.ExitError
		if errors.As(err, &exitErr) {
			exitCode = exitErr.ExitCode()
		} else {
			return execsupervisor.Status{}, err
		}
	}
	return execsupervisor.Status{
		ProtocolVersion: execsupervisor.ProtocolVersion, SupervisorSHA256: request.Attestation.SHA256,
		Quiescent: true, ChildExitCode: exitCode,
	}, nil
}

func TestExecuteHandlerDiscardsWorkspaceThatCrossesLiveQuota(t *testing.T) {
	originalRoot := workspaceRoot
	originalPolicy := servicePolicy
	workspaceRoot = t.TempDir()
	t.Cleanup(func() {
		workspaceRoot = originalRoot
		servicePolicy = originalPolicy
	})

	tests := []struct {
		name    string
		command string
		limits  sandboxruntime.WorkspaceLimits
	}{
		{
			name: "single oversized file", command: "printf 12345 > oversized.bin",
			limits: sandboxruntime.WorkspaceLimits{MaxFiles: 100, MaxFileBytes: 4, MaxBytes: 100},
		},
		{
			name: "total bytes", command: "printf 123 > one.bin; printf 456 > two.bin",
			limits: sandboxruntime.WorkspaceLimits{MaxFiles: 100, MaxFileBytes: 4, MaxBytes: 5},
		},
		{
			name: "symlink entries", command: "ln -s missing one; ln -s missing two",
			limits: sandboxruntime.WorkspaceLimits{MaxFiles: 1, MaxFileBytes: 100, MaxBytes: 100},
		},
	}
	for index, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			servicePolicy.WorkspaceLimits = test.limits
			taskID := fmt.Sprintf("quota-task-%d", index)
			workspaceID := fmt.Sprintf("quota-workspace-%d", index)
			response := postExecuteRequest(t, ExecuteRequest{
				WorkspaceID: workspaceID, TaskID: taskID,
			}, test.command)
			if response.Code != http.StatusInsufficientStorage || !strings.Contains(response.Body.String(), "workspace quota exceeded") {
				t.Fatalf("response = %d %s", response.Code, response.Body.String())
			}
			workspaceDir, err := executionWorkspacePath(workspaceID, taskID)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := os.Stat(workspaceDir); !os.IsNotExist(err) {
				t.Fatalf("unsafe workspace was retained: %v", err)
			}
		})
	}
}

func TestExecuteHandlerPublishesUnsafeIncarnationBeforeInvalidation(t *testing.T) {
	originalRoot := workspaceRoot
	originalPolicy := servicePolicy
	workspaceRoot = t.TempDir()
	servicePolicy.WorkspaceLimits = sandboxruntime.WorkspaceLimits{MaxFiles: 100, MaxFileBytes: 1, MaxBytes: 100}
	t.Cleanup(func() {
		workspaceRoot = originalRoot
		servicePolicy = originalPolicy
	})

	invalidated := false
	response := postExecuteRequestWithHooks(t, ExecuteRequest{
		WorkspaceID: "workspace-unsafe", TaskID: "task-unsafe",
	}, "printf 12 > oversized.bin", runTestSandboxCommand, func() { invalidated = true })

	if response.Code != http.StatusInsufficientStorage {
		t.Fatalf("response = %d %s, want workspace quota rejection", response.Code, response.Body.String())
	}
	if response.Header().Get("X-Agentarea-Executor-Unsafe") != "true" {
		t.Fatalf("unsafe response header = %q", response.Header().Get("X-Agentarea-Executor-Unsafe"))
	}
	if !invalidated {
		t.Fatal("unsafe executor incarnation was not invalidated after publishing the response")
	}
}

func TestExecuteHandlerRejectsDifferentExecutorIncarnationBeforeWorkspaceAccess(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	originalRoot := workspaceRoot
	workspaceRoot = t.TempDir()
	t.Cleanup(func() { workspaceRoot = originalRoot })
	req := ExecuteRequest{
		ExecutorIncarnation: "00000000-0000-4000-8000-000000000001",
		CommandBody:         "true",
		TaskID:              "task-incarnation",
		WorkspaceID:         "workspace-incarnation",
	}
	body, err := json.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}
	request := httptest.NewRequest(http.MethodPost, "/execute", bytes.NewReader(body))
	token, err := activationauth.SignFromEnv(activationauth.ScopeExecute, activationauth.Identity{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID, Generation: 0, FencingToken: 1,
	}, activationauth.BodySHA256(body), time.Now())
	if err != nil {
		t.Fatal(err)
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response := httptest.NewRecorder()
	executeHandler(response, request)
	if response.Code != http.StatusPreconditionFailed || !strings.Contains(response.Body.String(), "executor_incarnation_changed") {
		t.Fatalf("response = %d %s, want executor incarnation precondition", response.Code, response.Body.String())
	}
	if _, err := os.Stat(filepath.Join(workspaceRoot, req.WorkspaceID, req.TaskID)); !os.IsNotExist(err) {
		t.Fatalf("replacement executor touched workspace before rejecting request: %v", err)
	}
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

func TestDecodeExecuteRequestRejectsAllInlineFileShapes(t *testing.T) {
	for _, payload := range []string{
		`{"script_name":"cmd.sh","script_content":"true"}`,
		`{"script_name":"cmd.sh","script_content":"true","input_files":[]}`,
		`{"script_name":"cmd.sh","script_content":"true","content_base64":"ZmlsZQ=="}`,
		`{"command_path":".agentarea/commands/command.sh","args":["REDIS-ARGS-CANARY"]}`,
		`{"command_path":".agentarea/commands/command.sh","env":{"CANARY":"REDIS-ENV-CANARY"}}`,
		`{"command_path":".agentarea/commands/command.sh","script":"REDIS-SCRIPT-CANARY"}`,
	} {
		if _, err := decodeExecuteRequest(strings.NewReader(payload)); err == nil || !strings.Contains(err.Error(), "unsupported_contract_version") {
			t.Fatalf("inline-file payload accepted: %s; error = %v", payload, err)
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

	dir, err := resolveExecutionWorkspace("workspace-permissions", "task-permissions")
	if err != nil {
		t.Fatal(err)
	}
	for _, parent := range []string{
		filepath.Join(workspaceRoot, "workspaces"),
		filepath.Join(workspaceRoot, "workspaces", "workspace-permissions"),
		filepath.Join(workspaceRoot, "workspaces", "workspace-permissions", "tasks"),
	} {
		info, err := os.Stat(parent)
		if err != nil {
			t.Fatal(err)
		}
		if got := info.Mode().Perm(); got != 0o711 {
			t.Fatalf("parent %s permissions = %04o, want 0711", parent, got)
		}
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

func TestCollectArtifactsRequiresExplicitPaths(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "report.txt"), []byte("temporary"), 0o600); err != nil {
		t.Fatal(err)
	}
	if artifacts := collectArtifacts(dir, nil); artifacts != nil {
		t.Fatalf("collectArtifacts() = %v, want no implicit artifacts", artifacts)
	}
}

func TestPostExecutionInspectionHonorsSharedDeadline(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "artifact.txt"), []byte("artifact"), 0o600); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := collectArtifactsContext(ctx, dir, []string{"artifact.txt"}); !errors.Is(err, context.Canceled) {
		t.Fatalf("collectArtifactsContext() error = %v, want context.Canceled", err)
	}
	if _, err := collectWorkspaceChangesContext(ctx, dir, &workspace.Hydration{}); !errors.Is(err, context.Canceled) {
		t.Fatalf("collectWorkspaceChangesContext() error = %v, want context.Canceled", err)
	}
	limits := sandboxruntime.WorkspaceLimits{MaxFiles: 10, MaxFileBytes: 1024, MaxBytes: 2048}
	if err := enforceWorkspaceLimitsContext(ctx, dir, limits); !errors.Is(err, context.Canceled) {
		t.Fatalf("enforceWorkspaceLimitsContext() error = %v, want context.Canceled", err)
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
  "schema_version": 2,
  "managed_environment": "mutable",
  "image_version": "test-runtime",
  "python": {"version": "3.12.9", "executable": "/opt/runtime/venv/bin/python"},
  "node": {"version": "v22.1.0", "npm_version": "10.0.0"},
  "tools": {"git": "git version 2.0", "jq": "jq-1.7", "curl": "curl 8.0"},
  "packages": {"openpyxl": "3.1.5"},
  "features": {"browser": "none", "managed_environment_mutation": true, "arbitrary_workspace_code": true},
  "execution_supervisor": {"path":"/usr/local/bin/agentarea-exec-supervisor","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","protocol_version":1,"command_uid":10001,"command_gid":10001}
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
	if got["image_version"] != "test-runtime" {
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
