package builtin

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/activationauth"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
)

func TestDockerBackendForceRetirementDeletesExactTaskWorkspace(t *testing.T) {
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
		if err := activationauth.Verify(token, testActivationSecret, activationauth.ScopeCleanup, activationauth.Identity{
			WorkspaceID: workspaceID, TaskID: taskID, Generation: 0, FencingToken: 1,
		}, activationauth.BodySHA256(nil), time.Now()); err != nil {
			t.Errorf("Verify() error = %v", err)
			http.Error(response, "unauthorized", http.StatusUnauthorized)
			return
		}
		requests <- taskID
		response.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	backend := sharedExecutor(server.URL)
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
	backend := sharedExecutor(server.URL)

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

var testActivationSecret = []byte(strings.Repeat("s", 32))

// sharedExecutor is the development-only shared sandbox executor at url, opted
// into weak isolation. Sandbox paths refuse to run without the opt-in.
func sharedExecutor(url string) *Docker {
	return NewDocker(url, true, warmpool.Executor{Transport: http.DefaultTransport, Secret: testActivationSecret}, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

// The weak-isolation refusal belongs to sandbox execution, which is the thing
// that would run under it.
func TestSandboxExecutionRefusedWithoutExplicitDevelopmentOptIn(t *testing.T) {
	backend := NewDocker("http://executor.invalid", false, warmpool.Executor{Transport: http.DefaultTransport, Secret: testActivationSecret}, slog.New(slog.NewTextHandler(io.Discard, nil)))

	if _, err := backend.RuntimeManifest(context.Background()); err == nil || !strings.Contains(err.Error(), "development-only") {
		t.Fatalf("RuntimeManifest() error = %v, want explicit weak-isolation rejection", err)
	}
	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err == nil || !strings.Contains(err.Error(), "development-only") {
		t.Fatalf("RetireSandboxTask() error = %v, want explicit weak-isolation rejection", err)
	}
}

// A retired task directory is gone, so the next demand must hydrate the inputs again
// rather than trust the revision recorded for the deleted directory.
func TestDockerBackendRetirementForgetsTheHydratedRevision(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()
	backend := sharedExecutor(server.URL)
	retired, kept := dockerTaskKey("workspace-1", "task-1"), dockerTaskKey("workspace-1", "task-10")
	backend.hydrated[retired] = "revision-a"
	backend.hydrated[kept] = "revision-b"

	if err := backend.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err != nil {
		t.Fatal(err)
	}

	if revision, ok := backend.hydrated[retired]; ok {
		t.Fatalf("retired task still recorded as hydrated at %q", revision)
	}
	if backend.hydrated[kept] != "revision-b" {
		t.Fatal("retiring task-1 forgot task-10's hydration")
	}
}
