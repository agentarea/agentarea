package backends

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/config"
)

func TestDockerBackendForceRetirementDeletesExactTaskWorkspace(t *testing.T) {
	allowSharedExecutor(t)
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	requests := make(chan string, 3)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		workspaceID := request.URL.Query().Get("workspace_id")
		taskID := request.URL.Query().Get("task_id")
		if request.Method != http.MethodDelete || request.URL.Path != "/workspace/task" ||
			workspaceID != "workspace-1" || (taskID != "task-1" && taskID != "task-2") {
			t.Errorf("unexpected cleanup request: %s %s", request.Method, request.URL.String())
			http.Error(response, "bad request", http.StatusBadRequest)
			return
		}
		token, err := activationauth.BearerToken(request.Header.Get("Authorization"))
		if err != nil {
			t.Errorf("BearerToken() error = %v", err)
			http.Error(response, "unauthorized", http.StatusUnauthorized)
			return
		}
		if err := activationauth.VerifyFromEnv(token, activationauth.ScopeCleanup, activationauth.Identity{
			WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
		}, activationauth.BodySHA256(nil), time.Now()); err != nil {
			t.Errorf("VerifyFromEnv() error = %v", err)
			http.Error(response, "unauthorized", http.StatusUnauthorized)
			return
		}
		requests <- taskID
		response.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	backend := NewDockerBackend(&config.Config{Container: config.ContainerConfig{
		SandboxExecutorURL: server.URL,
	}}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", time.Hour); err != nil {
		t.Fatal(err)
	}
	select {
	case <-requests:
		t.Fatal("idle retirement deleted the task before its grace period")
	default:
	}
	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err != nil {
		t.Fatal(err)
	}
	select {
	case taskID := <-requests:
		if taskID != "task-1" {
			t.Fatalf("force retirement deleted %q, want task-1", taskID)
		}
	case <-time.After(time.Second):
		t.Fatal("force retirement did not reach the executor")
	}
	select {
	case <-requests:
		t.Fatal("cancelled idle timer produced a duplicate deletion")
	case <-time.After(20 * time.Millisecond):
	}

	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-2", 10*time.Millisecond); err != nil {
		t.Fatal(err)
	}
	select {
	case taskID := <-requests:
		if taskID != "task-2" {
			t.Fatalf("idle retirement deleted %q, want task-2", taskID)
		}
	case <-time.After(time.Second):
		t.Fatal("idle retirement did not reach the executor")
	}
}

func TestDockerBackendDoesNotRetireWorkspaceDuringActiveTransfer(t *testing.T) {
	allowSharedExecutor(t)
	t.Setenv(activationauth.SecretEnv, strings.Repeat("s", 32))
	deleteCalled := make(chan struct{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodDelete {
			http.Error(response, "unexpected method", http.StatusMethodNotAllowed)
			return
		}
		deleteCalled <- struct{}{}
		response.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()
	backend := NewDockerBackend(&config.Config{Container: config.ContainerConfig{
		SandboxExecutorURL: server.URL,
	}}, slog.New(slog.NewTextHandler(io.Discard, nil)))

	finish, err := backend.beginTaskOperation("workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err == nil || !strings.Contains(err.Error(), "active operations") {
		t.Fatalf("force retirement during transfer error = %v", err)
	}
	select {
	case <-deleteCalled:
		t.Fatal("workspace was deleted during active transfer")
	default:
	}
	finish()
	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err != nil {
		t.Fatal(err)
	}
	select {
	case <-deleteCalled:
	case <-time.After(time.Second):
		t.Fatal("workspace was not deleted after transfer finished")
	}
}

// allowSharedExecutor opts a test into the development-only shared sandbox
// executor. Sandbox paths refuse to run without it.
func allowSharedExecutor(t *testing.T) {
	t.Helper()
	t.Setenv("SANDBOX_SHARED_EXECUTOR_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT", "true")
}

// The weak-isolation refusal belongs to sandbox execution, which is the thing
// that would run under it.
func TestSandboxExecutionRefusedWithoutExplicitDevelopmentOptIn(t *testing.T) {
	t.Setenv("SANDBOX_SHARED_EXECUTOR_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT", "")
	cfg := &config.Config{}
	cfg.Container.SandboxExecutorURL = "http://executor.invalid"
	backend := NewDockerBackend(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))

	if _, err := backend.RuntimeManifest(context.Background()); err == nil || !strings.Contains(err.Error(), "development-only") {
		t.Fatalf("RuntimeManifest() error = %v, want explicit weak-isolation rejection", err)
	}
	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err == nil || !strings.Contains(err.Error(), "development-only") {
		t.Fatalf("RetireSandboxTask() error = %v, want explicit weak-isolation rejection", err)
	}
}

// MCP container lifecycle is the other half of this backend and shares nothing
// with the shared executor, so the same refusal must not reach it: a host that
// serves only MCP has no sandbox executor to opt into.
func TestMCPLifecycleIsNotGatedByTheSharedExecutorOptIn(t *testing.T) {
	t.Setenv("SANDBOX_SHARED_EXECUTOR_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT", "")
	cfg := &config.Config{}
	cfg.Container.Runtime = stubContainerRuntime(t)
	backend := NewDockerBackend(cfg, slog.New(slog.NewTextHandler(io.Discard, nil)))

	_, err := backend.ListInstances(context.Background())
	if err != nil && strings.Contains(err.Error(), "development-only") {
		t.Fatalf("ListInstances() error = %v, want no weak-isolation gate on MCP lifecycle", err)
	}
}

// stubContainerRuntime is a container runtime that answers every call with an
// empty result, so MCP lifecycle calls reach their own code rather than Docker.
func stubContainerRuntime(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "runtime")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexit 0\n"), 0o755); err != nil {
		t.Fatalf("writing stub runtime: %v", err)
	}
	return path
}
