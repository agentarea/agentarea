package backends

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/google/uuid"
)

func TestDockerBackendRehydratesAfterExecutorIncarnationChanges(t *testing.T) {
	var incarnationMu sync.RWMutex
	incarnation := uuid.NewString()
	var executeCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/health":
			incarnationMu.RLock()
			current := incarnation
			incarnationMu.RUnlock()
			_ = json.NewEncoder(response).Encode(map[string]string{
				"status": "waiting", "incarnation": current,
			})
		case "/execute":
			executeCalls.Add(1)
			_ = json.NewEncoder(response).Encode(warmpool.ExecuteResponse{ExitCode: 0})
		default:
			http.Error(response, "unexpected request", http.StatusNotFound)
		}
	}))
	defer server.Close()

	backend := NewDockerBackend(&config.Config{Container: config.ContainerConfig{
		SandboxExecutorURL: server.URL,
	}}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	var hydrations atomic.Int32
	hydrate := func(context.Context) error {
		hydrations.Add(1)
		return nil
	}
	revision := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	for index := 0; index < 2; index++ {
		if err := backend.EnsureWorkspaceHydrated(
			context.Background(), "workspace-1", "task-1",
			revision, hydrate,
		); err != nil {
			t.Fatal(err)
		}
	}
	if hydrations.Load() != 1 {
		t.Fatalf("hydrations before restart = %d, want 1", hydrations.Load())
	}

	incarnationMu.Lock()
	incarnation = uuid.NewString()
	incarnationMu.Unlock()
	if err := backend.EnsureWorkspaceHydrated(
		context.Background(), "workspace-1", "task-1",
		revision, hydrate,
	); err != nil {
		t.Fatal(err)
	}
	if hydrations.Load() != 2 {
		t.Fatalf("hydrations after restart = %d, want 2", hydrations.Load())
	}

	incarnationMu.Lock()
	incarnation = uuid.NewString()
	incarnationMu.Unlock()
	_, err := backend.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		CommandBody: "true",
	})
	if !errors.Is(err, sandboxruntime.ErrWorkspaceRehydration) {
		t.Fatalf("ExecuteSandbox() error = %v, want ErrWorkspaceRehydration", err)
	}
	if executeCalls.Load() != 0 {
		t.Fatalf("execute calls after incarnation change = %d, want 0", executeCalls.Load())
	}
}

func TestDockerBackendRejectsExecutorRestartBetweenHealthAndExecute(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, "0123456789abcdef0123456789abcdef")
	before := uuid.NewString()
	after := uuid.NewString()
	current := before
	var accepted atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/health":
			_ = json.NewEncoder(response).Encode(map[string]string{"status": "waiting", "incarnation": current})
			current = after
		case "/execute":
			var req warmpool.ExecuteRequest
			if err := json.NewDecoder(request.Body).Decode(&req); err != nil {
				t.Error(err)
			}
			if req.ExecutorIncarnation != current {
				http.Error(response, `{"error":"executor_incarnation_changed"}`, http.StatusPreconditionFailed)
				return
			}
			accepted.Add(1)
			_ = json.NewEncoder(response).Encode(warmpool.ExecuteResponse{ExitCode: 0})
		default:
			http.Error(response, "unexpected request", http.StatusNotFound)
		}
	}))
	defer server.Close()

	backend := NewDockerBackend(&config.Config{Container: config.ContainerConfig{
		SandboxExecutorURL: server.URL,
	}}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	_, err := backend.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		CommandBody: "true",
	})
	if !errors.Is(err, sandboxruntime.ErrWorkspaceRehydration) {
		t.Fatalf("ExecuteSandbox() error = %v, want ErrWorkspaceRehydration", err)
	}
	if accepted.Load() != 0 {
		t.Fatalf("commands accepted by replacement executor = %d, want 0", accepted.Load())
	}
}

func TestDockerBackendRejectsExecutorRestartBetweenHealthAndFileWrite(t *testing.T) {
	t.Setenv(activationauth.SecretEnv, "0123456789abcdef0123456789abcdef")
	before := uuid.NewString()
	after := uuid.NewString()
	current := before
	var accepted atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/health":
			_ = json.NewEncoder(response).Encode(map[string]string{"status": "waiting", "incarnation": current})
			current = after
		case "/files/content":
			if request.URL.Query().Get("executor_incarnation") != current {
				http.Error(response, `{"error":"executor_incarnation_changed"}`, http.StatusPreconditionFailed)
				return
			}
			accepted.Add(1)
			_ = json.NewEncoder(response).Encode(warmpool.FilePutResponse{Path: "input.txt", Size: 1})
		default:
			http.Error(response, "unexpected request", http.StatusNotFound)
		}
	}))
	defer server.Close()

	backend := NewDockerBackend(&config.Config{Container: config.ContainerConfig{
		SandboxExecutorURL: server.URL,
	}}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	_, err := backend.SandboxFileUpload(context.Background(), sandboxruntime.FileUpload{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "input.txt", Size: 1,
		SHA256: "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
		Mode:   0o600,
	}, strings.NewReader("x"))
	if !errors.Is(err, sandboxruntime.ErrWorkspaceRehydration) {
		t.Fatalf("SandboxFileUpload() error = %v, want ErrWorkspaceRehydration", err)
	}
	if accepted.Load() != 0 {
		t.Fatalf("file writes accepted by replacement executor = %d, want 0", accepted.Load())
	}
}

func TestDockerBackendSerializesConcurrentHydration(t *testing.T) {
	incarnation := uuid.NewString()
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/health" {
			http.Error(response, "unexpected request", http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(response).Encode(map[string]string{
			"status": "waiting", "incarnation": incarnation,
		})
	}))
	defer server.Close()
	backend := NewDockerBackend(&config.Config{Container: config.ContainerConfig{
		SandboxExecutorURL: server.URL,
	}}, slog.New(slog.NewTextHandler(io.Discard, nil)))
	var calls atomic.Int32
	entered := make(chan struct{})
	release := make(chan struct{})
	hydrate := func(context.Context) error {
		if calls.Add(1) == 1 {
			close(entered)
			<-release
		}
		return nil
	}
	revision := "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	errorsByCaller := make(chan error, 2)
	for range 2 {
		go func() {
			errorsByCaller <- backend.EnsureWorkspaceHydrated(
				context.Background(), "workspace-1", "task-1",
				revision, hydrate,
			)
		}()
	}
	<-entered
	close(release)
	for range 2 {
		if err := <-errorsByCaller; err != nil {
			t.Fatal(err)
		}
	}
	if calls.Load() != 1 {
		t.Fatalf("concurrent hydration calls = %d, want 1", calls.Load())
	}
}
