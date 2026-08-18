package connectorsandbox

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
)

type fenceKey struct{}

type fakeRuntime struct {
	mu sync.Mutex

	executions int
	puts       int
	gets       int
	lists      int
	ensures    int
	hydrates   int
	retires    int

	lastWorkspace string
	lastTask      string
	lastExecute   sandboxcontract.ExecuteRequest
	files         map[string][]byte
	response      *sandboxcontract.ExecuteResponse
	execute       func(context.Context) error
}

func newFakeRuntime() *fakeRuntime {
	return &fakeRuntime{
		files:    make(map[string][]byte),
		response: &sandboxcontract.ExecuteResponse{ExitCode: 0},
	}
}

func (r *fakeRuntime) BeginOperation(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	if workspaceID == "" || taskID == "" {
		return nil, nil, fmt.Errorf("missing identity")
	}
	r.mu.Lock()
	r.lastWorkspace, r.lastTask = workspaceID, taskID
	r.mu.Unlock()
	return context.WithValue(ctx, fenceKey{}, workspaceID+"/"+taskID), func() {}, nil
}

func (r *fakeRuntime) ExecuteSandbox(ctx context.Context, request sandboxcontract.ExecuteRequest) (*sandboxcontract.ExecuteResponse, error) {
	if err := r.fenced(ctx, request.WorkspaceID, request.TaskID); err != nil {
		return nil, err
	}
	r.mu.Lock()
	r.executions++
	r.lastExecute = request
	fn := r.execute
	response := *r.response
	r.mu.Unlock()
	if fn != nil {
		if err := fn(ctx); err != nil {
			return nil, err
		}
	}
	return &response, nil
}

func (r *fakeRuntime) SandboxFilePut(context.Context, sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	return nil, errors.New("raw file put should not be used")
}

func (r *fakeRuntime) SandboxFileGet(context.Context, string, string, string) (*sandboxcontract.FileGetResponse, error) {
	return nil, errors.New("raw file get should not be used")
}

func (r *fakeRuntime) SandboxFileList(context.Context, string, string, string) (*sandboxcontract.FileListResponse, error) {
	return nil, errors.New("raw file list should not be used")
}

func (r *fakeRuntime) SandboxFileUpload(context.Context, sandboxruntime.FileUpload, io.Reader) (*sandboxruntime.FileWriteResult, error) {
	return nil, errors.New("raw file upload should not be used")
}

func (r *fakeRuntime) SandboxFileDownload(context.Context, string, string, string) (*sandboxruntime.FileDownload, error) {
	return nil, errors.New("raw file download should not be used")
}

func (r *fakeRuntime) EnsureWorkspaceHydrated(ctx context.Context, workspaceID, taskID, _ string, hydrate func(context.Context) error) error {
	if err := r.fenced(ctx, workspaceID, taskID); err != nil {
		return err
	}
	r.mu.Lock()
	r.hydrates++
	r.mu.Unlock()
	return hydrate(ctx)
}

func (r *fakeRuntime) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, _ time.Duration) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.retires++
	r.lastWorkspace, r.lastTask = workspaceID, taskID
	return nil
}

func (r *fakeRuntime) RuntimeManifest(context.Context) (*runtimeinfo.Manifest, error) {
	return nil, nil
}

func (r *fakeRuntime) fenced(ctx context.Context, workspaceID, taskID string) error {
	if got, _ := ctx.Value(fenceKey{}).(string); got != workspaceID+"/"+taskID {
		return fmt.Errorf("runtime operation was not fenced for %s/%s", workspaceID, taskID)
	}
	return nil
}

var _ sandboxruntime.ManagedRuntime = (*fakeRuntime)(nil)

type richFakeRuntime struct{ *fakeRuntime }

func (r *richFakeRuntime) EnsureWorkspace(ctx context.Context, workspaceID, taskID string) error {
	if err := r.fenced(ctx, workspaceID, taskID); err != nil {
		return err
	}
	r.mu.Lock()
	r.ensures++
	r.mu.Unlock()
	return nil
}

func (r *richFakeRuntime) PutWorkspaceFile(ctx context.Context, request sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	if err := r.fenced(ctx, request.WorkspaceID, request.TaskID); err != nil {
		return nil, err
	}
	content, err := base64.StdEncoding.DecodeString(request.ContentBase64)
	if err != nil {
		return nil, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.puts++
	r.files[request.Path] = append([]byte(nil), content...)
	return &sandboxcontract.FilePutResponse{Path: request.Path, Size: int64(len(content))}, nil
}

func (r *richFakeRuntime) UploadWorkspaceFile(context.Context, sandboxruntime.FileUpload, io.Reader) (*sandboxruntime.FileWriteResult, error) {
	return nil, errors.New("streamed file upload is outside adapter scope")
}

func (r *richFakeRuntime) GetWorkspaceFile(context.Context, sandboxruntime.WorkspaceFileRead) (*sandboxcontract.FileGetResponse, error) {
	return nil, errors.New("inline file get should not be used")
}

func (r *richFakeRuntime) OpenWorkspaceFile(ctx context.Context, request sandboxruntime.WorkspaceFileRead) (*sandboxruntime.FileDownload, error) {
	if err := r.fenced(ctx, request.WorkspaceID, request.TaskID); err != nil {
		return nil, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.gets++
	content, exists := r.files[request.Path]
	if !exists {
		return nil, sandboxcontract.ErrFileNotFound
	}
	return &sandboxruntime.FileDownload{Content: io.NopCloser(bytes.NewReader(content)), Size: int64(len(content))}, nil
}

func (r *richFakeRuntime) ListWorkspaceFiles(ctx context.Context, request sandboxruntime.WorkspaceFileList) (*sandboxcontract.FileListResponse, error) {
	if err := r.fenced(ctx, request.WorkspaceID, request.TaskID); err != nil {
		return nil, err
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.lists++
	paths := make([]string, 0, len(r.files))
	for path := range r.files {
		paths = append(paths, path)
	}
	return &sandboxcontract.FileListResponse{Paths: paths}, nil
}

var _ sandboxruntime.WorkspaceFileReader = (*richFakeRuntime)(nil)
var _ sandboxruntime.WorkspaceFileWriter = (*richFakeRuntime)(nil)

func testDispatcher(t *testing.T, runtime sandboxruntime.ManagedRuntime, cfg Config) *Dispatcher {
	t.Helper()
	dispatcher, err := New(runtime, cfg)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}
	return dispatcher
}

func executeCommand(id, body string) Command {
	return Command{
		Operation:   OperationExecute,
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		ExecutionID: id,
		Execute:     &sandboxcontract.ExecuteRequest{CommandBody: body},
	}
}

func TestDispatcherReplaysCompletedExecutionWithoutDuplicateSideEffects(t *testing.T) {
	runtime := newFakeRuntime()
	runtime.response.Stdout = "result"
	dispatcher := testDispatcher(t, runtime, Config{})

	first, err := dispatcher.Dispatch(context.Background(), executeCommand("execution-1", "echo once"))
	if err != nil {
		t.Fatalf("first Dispatch() error = %v", err)
	}
	first.Execute.Stdout = "caller mutation"
	second, err := dispatcher.Dispatch(context.Background(), executeCommand("execution-1", "echo once"))
	if err != nil {
		t.Fatalf("replay Dispatch() error = %v", err)
	}
	if second.Execute.Stdout != "result" {
		t.Fatalf("replayed stdout = %q, want original result", second.Execute.Stdout)
	}
	runtime.mu.Lock()
	executions := runtime.executions
	runtime.mu.Unlock()
	if executions != 1 {
		t.Fatalf("runtime executions = %d, want 1", executions)
	}
	if _, err := dispatcher.Dispatch(context.Background(), executeCommand("execution-1", "echo different")); !errors.Is(err, ErrExecutionIDConflict) {
		t.Fatalf("changed replay error = %v, want ErrExecutionIDConflict", err)
	}
}

func TestDispatcherFencesWorkspaceOperationsAndRejectsCrossTaskPayloads(t *testing.T) {
	runtime := &richFakeRuntime{fakeRuntime: newFakeRuntime()}
	dispatcher := testDispatcher(t, runtime, Config{})

	if _, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationWorkspaceEnsure, WorkspaceID: "workspace-1", TaskID: "task-1",
	}); err != nil {
		t.Fatalf("ensure workspace: %v", err)
	}
	hydrated := false
	if _, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationWorkspaceHydrate, WorkspaceID: "workspace-1", TaskID: "task-1",
		Hydration: &HydrationRequest{Revision: strings.Repeat("a", 64), Hydrate: func(ctx context.Context) error {
			if err := runtime.fenced(ctx, "workspace-1", "task-1"); err != nil {
				return err
			}
			hydrated = true
			return nil
		}},
	}); err != nil {
		t.Fatalf("hydrate workspace: %v", err)
	}
	if !hydrated {
		t.Fatal("hydrate callback was not called")
	}

	encoded := base64.StdEncoding.EncodeToString([]byte("ok"))
	_, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationFilePut, WorkspaceID: "workspace-1", TaskID: "task-1",
		FilePut: &sandboxcontract.FilePutRequest{WorkspaceID: "workspace-2", Path: "out.txt", ContentBase64: encoded},
	})
	if err == nil || !strings.Contains(err.Error(), "does not match") {
		t.Fatalf("cross-workspace put error = %v, want identity mismatch", err)
	}
	runtime.mu.Lock()
	puts := runtime.puts
	runtime.mu.Unlock()
	if puts != 0 {
		t.Fatalf("file put side effects = %d, want 0", puts)
	}
	if _, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationFilePut, WorkspaceID: "workspace-1", TaskID: "task-1",
		FilePut: &sandboxcontract.FilePutRequest{Path: "out.txt", ContentBase64: encoded},
	}); err != nil {
		t.Fatalf("file put: %v", err)
	}
	listed, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationFileList, WorkspaceID: "workspace-1", TaskID: "task-1", Prefix: "",
	})
	if err != nil || len(listed.FileList.Paths) != 1 || listed.FileList.Paths[0] != "out.txt" {
		t.Fatalf("file list result = %#v, error = %v", listed.FileList, err)
	}
	got, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationFileGet, WorkspaceID: "workspace-1", TaskID: "task-1", Path: "out.txt",
	})
	if err != nil {
		t.Fatalf("file get: %v", err)
	}
	content, decodeErr := base64.StdEncoding.DecodeString(got.FileGet.ContentBase64)
	if decodeErr != nil || string(content) != "ok" {
		t.Fatalf("file get content = %q, decode error = %v", content, decodeErr)
	}

	if _, err := dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationTaskRetire, WorkspaceID: "workspace-1", TaskID: "task-1",
	}); err != nil {
		t.Fatalf("retire task: %v", err)
	}
	runtime.mu.Lock()
	ensures, hydrates, retires := runtime.ensures, runtime.hydrates, runtime.retires
	runtime.mu.Unlock()
	if ensures != 1 || hydrates != 1 || retires != 1 {
		t.Fatalf("ensure/hydrate/retire = %d/%d/%d, want 1/1/1", ensures, hydrates, retires)
	}
}

func TestDispatcherHonorsCancellationAndReplaysCompletedFailure(t *testing.T) {
	runtime := newFakeRuntime()
	runtime.execute = func(ctx context.Context) error {
		<-ctx.Done()
		return ctx.Err()
	}
	dispatcher := testDispatcher(t, runtime, Config{DefaultTimeout: 10 * time.Millisecond, MaxTimeout: 20 * time.Millisecond})
	command := executeCommand("execution-timeout", "wait")
	command.Timeout = 10 * time.Millisecond
	_, err := dispatcher.Dispatch(context.Background(), command)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Dispatch() error = %v, want deadline exceeded", err)
	}
	_, replayErr := dispatcher.Dispatch(context.Background(), command)
	if !errors.Is(replayErr, context.DeadlineExceeded) {
		t.Fatalf("replayed error = %v, want stable deadline error", replayErr)
	}
	runtime.mu.Lock()
	executions := runtime.executions
	runtime.mu.Unlock()
	if executions != 1 {
		t.Fatalf("runtime executions = %d, want 1", executions)
	}
}

func TestDispatcherBoundsInlineOutputAndFiles(t *testing.T) {
	runtime := &richFakeRuntime{fakeRuntime: newFakeRuntime()}
	runtime.response.Stdout = "three"
	runtime.files["large.txt"] = []byte("three")
	dispatcher := testDispatcher(t, runtime, Config{
		MaxInlineFileBytes: 2, MaxInlineOutputBytes: 2, DefaultTimeout: time.Second, MaxTimeout: time.Second,
	})

	result, err := dispatcher.Dispatch(context.Background(), executeCommand("execution-output", "echo output"))
	if err != nil {
		t.Fatalf("execute: %v", err)
	}
	if result.Execute.Stdout != "th" || !result.Execute.StdoutTruncated {
		t.Fatalf("bounded output = %#v", result.Execute)
	}
	encoded := base64.StdEncoding.EncodeToString([]byte("three"))
	_, err = dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationFilePut, WorkspaceID: "workspace-1", TaskID: "task-1",
		FilePut: &sandboxcontract.FilePutRequest{Path: "large.txt", ContentBase64: encoded},
	})
	if !errors.Is(err, ErrInlinePayloadLimit) {
		t.Fatalf("oversized file put error = %v, want limit", err)
	}
	_, err = dispatcher.Dispatch(context.Background(), Command{
		Operation: OperationFileGet, WorkspaceID: "workspace-1", TaskID: "task-1", Path: "large.txt",
	})
	if !errors.Is(err, ErrInlinePayloadLimit) {
		t.Fatalf("oversized file get error = %v, want limit", err)
	}
	runtime.mu.Lock()
	puts := runtime.puts
	runtime.mu.Unlock()
	if puts != 0 {
		t.Fatalf("oversized put invoked runtime %d times, want 0", puts)
	}
}

func TestDispatcherReportsMissingOptionalCapabilities(t *testing.T) {
	dispatcher := testDispatcher(t, newFakeRuntime(), Config{})
	for _, command := range []Command{
		{Operation: OperationWorkspaceEnsure, WorkspaceID: "workspace-1", TaskID: "task-1"},
		{Operation: OperationFilePut, WorkspaceID: "workspace-1", TaskID: "task-1", FilePut: &sandboxcontract.FilePutRequest{}},
		{Operation: OperationFileGet, WorkspaceID: "workspace-1", TaskID: "task-1", Path: "x.txt"},
	} {
		if _, err := dispatcher.Dispatch(context.Background(), command); !errors.Is(err, ErrCapabilityUnavailable) {
			t.Errorf("%s error = %v, want capability error", command.Operation, err)
		}
	}
}
