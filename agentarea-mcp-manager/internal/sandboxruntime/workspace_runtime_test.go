package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxworkspace"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

type fakeWorkspaceProvider struct {
	mount         *sandboxworkspace.Mount
	ensureCalls   int
	additions     map[string][]workspace.Entry
	additionCalls []string
}

func (p *fakeWorkspaceProvider) Ensure(context.Context, string, string) (*sandboxworkspace.Mount, error) {
	p.ensureCalls++
	return p.mount, nil
}

func (p *fakeWorkspaceProvider) HydrationAdditions(_ context.Context, _, _, fromRevision, toRevision string) ([]workspace.Entry, error) {
	p.additionCalls = append(p.additionCalls, fromRevision+"->"+toRevision)
	if entries, ok := p.additions[fromRevision+"->"+toRevision]; ok {
		return entries, nil
	}
	return nil, fmt.Errorf("%w: hydration view %s is not an additive attachment change from %s", workspace.ErrWorkspaceConflict, toRevision, fromRevision)
}

type fakeWorkspaceRuntime struct {
	files              map[string][]byte
	executeCalls       int
	putCalls           []warmpool.FilePutRequest
	workspaceGone      bool
	hydrated           map[string]string
	modes              map[string]fs.FileMode
	fences             int
	fenceReleases      int
	executeMissingOnce bool
	executedInputs     []string
}

// BeginOperation records that the decorator took one fence for the whole
// composite operation rather than letting each step take its own.
func (r *fakeWorkspaceRuntime) BeginOperation(
	ctx context.Context,
	_, _ string,
) (context.Context, func(), error) {
	r.fences++
	return ctx, func() { r.fenceReleases++ }, nil
}

func (r *fakeWorkspaceRuntime) ExecuteSandbox(context.Context, warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	r.executeCalls++
	if r.executeMissingOnce {
		r.executeMissingOnce = false
		r.files = map[string][]byte{}
		r.hydrated = map[string]string{}
		return nil, ErrWorkspaceRehydration
	}
	r.executedInputs = append(r.executedInputs, string(r.files["inputs/customer.txt"]))
	return &warmpool.ExecuteResponse{ExitCode: 0}, nil
}

func (r *fakeWorkspaceRuntime) SandboxFilePut(_ context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	r.workspaceGone = false
	r.putCalls = append(r.putCalls, req)
	decoded, err := io.ReadAll(base64.NewDecoder(base64.StdEncoding, strings.NewReader(req.ContentBase64)))
	if err != nil {
		return nil, err
	}
	if r.files == nil {
		r.files = map[string][]byte{}
	}
	r.files[req.Path] = decoded
	return &warmpool.FilePutResponse{Path: req.Path, Size: int64(len(decoded))}, nil
}

func (r *fakeWorkspaceRuntime) SandboxFileUpload(_ context.Context, req FileUpload, source io.Reader) (*FileWriteResult, error) {
	content, err := io.ReadAll(source)
	if err != nil {
		return nil, err
	}
	digest := sha256.Sum256(content)
	if int64(len(content)) != req.Size || hex.EncodeToString(digest[:]) != req.SHA256 {
		return nil, errors.New("streamed file identity mismatch")
	}
	r.workspaceGone = false
	if r.files == nil {
		r.files = map[string][]byte{}
	}
	r.files[req.Path] = content
	if r.modes == nil {
		r.modes = make(map[string]fs.FileMode)
	}
	r.modes[req.Path] = req.Mode
	r.putCalls = append(r.putCalls, warmpool.FilePutRequest{WorkspaceID: req.WorkspaceID, TaskID: req.TaskID, Path: req.Path})
	return &FileWriteResult{Path: req.Path, Size: req.Size}, nil
}

func (r *fakeWorkspaceRuntime) SandboxFileGet(_ context.Context, _, _, path string) (*warmpool.FileGetResponse, error) {
	if r.workspaceGone {
		return nil, warmpool.ErrTaskWorkspaceGone
	}
	content, ok := r.files[path]
	if !ok {
		return nil, warmpool.ErrFileNotFound
	}
	return &warmpool.FileGetResponse{ContentBase64: base64.StdEncoding.EncodeToString(content), Size: int64(len(content))}, nil
}

func (r *fakeWorkspaceRuntime) SandboxFileDownload(_ context.Context, _, _, path string) (*FileDownload, error) {
	if r.workspaceGone {
		return nil, warmpool.ErrTaskWorkspaceGone
	}
	content, ok := r.files[path]
	if !ok {
		return nil, warmpool.ErrFileNotFound
	}
	return &FileDownload{Content: io.NopCloser(bytes.NewReader(content)), Size: int64(len(content)), Mode: 0o600}, nil
}

func (r *fakeWorkspaceRuntime) SandboxFileList(context.Context, string, string, string) (*warmpool.FileListResponse, error) {
	paths := make([]string, 0, len(r.files))
	for path := range r.files {
		paths = append(paths, path)
	}
	return &warmpool.FileListResponse{Paths: paths}, nil
}

func (*fakeWorkspaceRuntime) RuntimeManifest(context.Context) (*runtimeinfo.Manifest, error) {
	return nil, errors.New("not used")
}

func (r *fakeWorkspaceRuntime) EnsureWorkspaceHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
	advance func(context.Context, string) error,
) error {
	key := workspaceID + "\x00" + taskID
	if r.hydrated == nil {
		r.hydrated = make(map[string]string)
	}
	if r.hydrated[key] == revision {
		return nil
	}
	if r.hydrated[key] != "" {
		if err := advance(ctx, r.hydrated[key]); err != nil {
			return fmt.Errorf("live sandbox input manifest changed: %w", err)
		}
		r.hydrated[key] = revision
		return nil
	}
	if err := hydrate(ctx); err != nil {
		return err
	}
	r.hydrated[key] = revision
	return nil
}

func (*fakeWorkspaceRuntime) RetireSandboxTask(context.Context, string, string, time.Duration) error {
	return nil
}

func TestWorkspaceRuntimeStreamingReadHoldsDemandFenceUntilClose(t *testing.T) {
	revision := strings.Repeat("a", 64)
	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID: "workspace-1", TaskID: "task-1", Root: WorkspaceRoot,
		RevisionSHA256: revision,
		Hydration:      workspace.Hydration{RevisionSHA256: revision},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{"result.txt": []byte("result")}}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	download, err := runtime.OpenWorkspaceFile(context.Background(), WorkspaceFileRead{
		WorkspaceFileDemand: WorkspaceFileDemand{
			WorkspaceID: "workspace-1", TaskID: "task-1", Ensure: true,
		},
		Path: "result.txt",
	})
	if err != nil {
		t.Fatal(err)
	}
	if dataPlane.fences != 1 || dataPlane.fenceReleases != 0 {
		t.Fatalf("fence before close = acquired:%d released:%d", dataPlane.fences, dataPlane.fenceReleases)
	}
	if _, err := io.ReadAll(download.Content); err != nil {
		t.Fatal(err)
	}
	if dataPlane.fenceReleases != 0 {
		t.Fatal("stream read released the demand fence before Close")
	}
	if err := download.Content.Close(); err != nil {
		t.Fatal(err)
	}
	if err := download.Content.Close(); err != nil {
		t.Fatal(err)
	}
	if dataPlane.fenceReleases != 1 {
		t.Fatalf("fence releases after Close = %d, want exactly 1", dataPlane.fenceReleases)
	}
}

func TestWorkspaceRuntimeMaterializesInputsBeforeExecutionOnce(t *testing.T) {
	content := []byte("customer input")
	digest := sha256.Sum256(content)
	revisionSHA256 := strings.Repeat("a", 64)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		response.WriteHeader(http.StatusOK)
		_, _ = response.Write(content)
	}))
	defer server.Close()

	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Root:           WorkspaceRoot,
		Generation:     7,
		ManifestSHA256: strings.Repeat("b", 64),
		RevisionSHA256: revisionSHA256,
		Hydration: workspace.Hydration{
			Generation:     7,
			ManifestSHA256: strings.Repeat("b", 64),
			RevisionSHA256: revisionSHA256,
			Downloads: []workspace.Download{{
				RelativePath: "inputs/customer.txt",
				URL:          server.URL,
				SHA256:       hex.EncodeToString(digest[:]),
				Size:         int64(len(content)),
				Mode:         0o755,
			}},
		},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}, workspaceGone: true}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatalf("NewWorkspaceRuntime() error = %v", err)
	}

	request := warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		CommandBody: "cat inputs/customer.txt",
	}
	if _, err := runtime.ExecuteSandbox(context.Background(), request); err != nil {
		t.Fatalf("first ExecuteSandbox() error = %v", err)
	}
	dataPlane.files["inputs/customer.txt"] = []byte("agent working copy")
	if _, err := runtime.ExecuteSandbox(context.Background(), request); err != nil {
		t.Fatalf("second ExecuteSandbox() error = %v", err)
	}
	if got := string(dataPlane.files["inputs/customer.txt"]); got != "agent working copy" {
		t.Fatalf("second demand overwrote the agent's working copy: %q", got)
	}
	if got := dataPlane.modes["inputs/customer.txt"]; got != 0o755 {
		t.Fatalf("hydrated mode = %o, want 755", got)
	}
	if dataPlane.executeCalls != 2 {
		t.Fatalf("execute calls = %d, want 2", dataPlane.executeCalls)
	}
	// Hydration state belongs to the control plane and is not written into the
	// agent-visible workspace. Only the immutable input is copied once.
	if len(dataPlane.putCalls) != 1 {
		t.Fatalf("put calls = %d, want 1", len(dataPlane.putCalls))
	}
}

func TestWorkspaceRuntimeRehydratesOnNextDemandAfterProviderSessionDisappears(t *testing.T) {
	content := []byte("durable input")
	digest := sha256.Sum256(content)
	revision := strings.Repeat("a", 64)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		_, _ = response.Write(content)
	}))
	defer server.Close()
	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID: "workspace-1", TaskID: "task-1", Root: WorkspaceRoot,
		Generation: 1, ManifestSHA256: strings.Repeat("b", 64), RevisionSHA256: revision,
		Hydration: workspace.Hydration{
			Generation: 1, ManifestSHA256: strings.Repeat("b", 64), RevisionSHA256: revision,
			Downloads: []workspace.Download{{
				RelativePath: "inputs/customer.txt", URL: server.URL,
				SHA256: hex.EncodeToString(digest[:]), Size: int64(len(content)), Mode: 0o600,
			}},
		},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}, executeMissingOnce: true}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	request := warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "cat inputs/customer.txt",
	}

	if _, err := runtime.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrWorkspaceRehydration) {
		t.Fatalf("first ExecuteSandbox() error = %v, want ErrWorkspaceRehydration", err)
	}
	if len(dataPlane.executedInputs) != 0 {
		t.Fatalf("disappeared session unexpectedly retried command: %v", dataPlane.executedInputs)
	}
	if _, err := runtime.ExecuteSandbox(context.Background(), request); err != nil {
		t.Fatalf("next demand ExecuteSandbox() error = %v", err)
	}
	if len(dataPlane.executedInputs) != 1 || dataPlane.executedInputs[0] != string(content) {
		t.Fatalf("next demand executed with inputs %v", dataPlane.executedInputs)
	}
	if len(dataPlane.putCalls) != 2 {
		t.Fatalf("input hydrations = %d, want one per provider session", len(dataPlane.putCalls))
	}
}

func TestWorkspaceRuntimeWithManagerDoesNotReplaceMissingSessionWithinSameDemand(t *testing.T) {
	content := []byte("durable input")
	digest := sha256.Sum256(content)
	revision := strings.Repeat("a", 64)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		_, _ = response.Write(content)
	}))
	defer server.Close()

	workspaces := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID: "workspace-1", TaskID: "task-1", Root: WorkspaceRoot,
		Generation: 1, ManifestSHA256: strings.Repeat("b", 64), RevisionSHA256: revision,
		Hydration: workspace.Hydration{
			Generation: 1, ManifestSHA256: strings.Repeat("b", 64), RevisionSHA256: revision,
			Downloads: []workspace.Download{{
				RelativePath: "inputs/customer.txt", URL: server.URL,
				SHA256: hex.EncodeToString(digest[:]), Size: int64(len(content)), Mode: 0o600,
			}},
		},
	}}
	manager, provider := newTestManager(t)
	// Cold-demand call order is: hydration renew, upload renew, post-upload
	// renew, then execute renew. Simulate the provider session disappearing at
	// the boundary immediately before command execution.
	provider.renewErrOn = 4
	runtime, err := NewWorkspaceRuntime(manager, workspaces)
	if err != nil {
		t.Fatal(err)
	}
	request := warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "cat inputs/customer.txt",
	}

	if _, err := runtime.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrWorkspaceRehydration) {
		t.Fatalf("first ExecuteSandbox() error = %v, want ErrWorkspaceRehydration", err)
	}
	provider.mu.Lock()
	if provider.creates != 1 || len(provider.executeIDs) != 0 {
		provider.mu.Unlock()
		t.Fatalf("same demand created or executed a replacement: creates=%d executions=%v", provider.creates, provider.executeIDs)
	}
	provider.mu.Unlock()

	if _, err := runtime.ExecuteSandbox(context.Background(), request); err != nil {
		t.Fatalf("next demand ExecuteSandbox() error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 || len(provider.executeIDs) != 1 || provider.executeIDs[0] != "sandbox-2" {
		t.Fatalf("next demand creates=%d executions=%v, want replacement sandbox-2", provider.creates, provider.executeIDs)
	}
	if provider.puts != 2 {
		t.Fatalf("input uploads = %d, want one per provider session", provider.puts)
	}
}

func TestWorkspaceRuntimeRejectsTamperedInputBeforeExecution(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		_, _ = response.Write([]byte("tampered"))
	}))
	defer server.Close()

	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Root:           WorkspaceRoot,
		Generation:     1,
		ManifestSHA256: strings.Repeat("c", 64),
		RevisionSHA256: strings.Repeat("d", 64),
		Hydration: workspace.Hydration{Generation: 1, ManifestSHA256: strings.Repeat("c", 64), RevisionSHA256: strings.Repeat("d", 64), Downloads: []workspace.Download{{
			RelativePath: "inputs/a.txt",
			URL:          server.URL,
			SHA256:       "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			Size:         8,
		}}},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	_, err = runtime.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		CommandBody: "true",
	})
	if err == nil {
		t.Fatal("ExecuteSandbox() accepted an input with a mismatched digest")
	}
	if dataPlane.executeCalls != 0 {
		t.Fatalf("execute calls = %d, want 0", dataPlane.executeCalls)
	}
}

func TestWorkspaceRuntimeRejectsNonCanonicalInputPathFromProvider(t *testing.T) {
	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Root:           WorkspaceRoot,
		Generation:     1,
		ManifestSHA256: strings.Repeat("a", 64),
		RevisionSHA256: strings.Repeat("b", 64),
		Hydration: workspace.Hydration{
			Generation:     1,
			ManifestSHA256: strings.Repeat("a", 64),
			RevisionSHA256: strings.Repeat("b", 64),
			Downloads: []workspace.Download{{
				RelativePath: "inputs/../report.txt",
				URL:          "http://127.0.0.1/should-not-be-requested",
				SHA256:       strings.Repeat("c", 64),
				Size:         1,
			}},
		},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err == nil || !strings.Contains(err.Error(), "non-input path") {
		t.Fatalf("EnsureWorkspace() error = %v, want non-input path rejection", err)
	}
	if len(dataPlane.putCalls) != 0 {
		t.Fatalf("invalid provider path produced %d file writes", len(dataPlane.putCalls))
	}
}

func TestWorkspaceRuntimeDoesNotRehydrateWhenOnlyContainingManifestChanges(t *testing.T) {
	revisionSHA256 := strings.Repeat("d", 64)
	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Root:           WorkspaceRoot,
		Generation:     7,
		ManifestSHA256: strings.Repeat("a", 64),
		RevisionSHA256: revisionSHA256,
		Hydration: workspace.Hydration{
			Generation:     7,
			ManifestSHA256: strings.Repeat("a", 64),
			RevisionSHA256: revisionSHA256,
		},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}

	provider.mount.Generation = 8
	provider.mount.ManifestSHA256 = strings.Repeat("b", 64)
	provider.mount.Hydration.Generation = 8
	provider.mount.Hydration.ManifestSHA256 = strings.Repeat("b", 64)
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}
	if len(dataPlane.putCalls) != 0 {
		t.Fatalf("put calls = %d, want no agent-visible marker", len(dataPlane.putCalls))
	}
}

func TestWorkspaceRuntimeRejectsInputRevisionChangeAfterMaterialization(t *testing.T) {
	content := []byte("new input")
	digest := sha256.Sum256(content)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		_, _ = response.Write(content)
	}))
	defer server.Close()

	initialManifestSHA256 := hex.EncodeToString(make([]byte, sha256.Size))
	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Root:           WorkspaceRoot,
		Generation:     7,
		ManifestSHA256: initialManifestSHA256,
		RevisionSHA256: strings.Repeat("a", 64),
		Hydration: workspace.Hydration{
			Generation:     7,
			ManifestSHA256: initialManifestSHA256,
			RevisionSHA256: strings.Repeat("a", 64),
		},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}

	provider.mount.ManifestSHA256 = hex.EncodeToString(digest[:])
	provider.mount.RevisionSHA256 = strings.Repeat("b", 64)
	provider.mount.Hydration = workspace.Hydration{
		Generation:     7,
		ManifestSHA256: provider.mount.ManifestSHA256,
		RevisionSHA256: provider.mount.RevisionSHA256,
		Downloads: []workspace.Download{{
			RelativePath: "inputs/new.txt",
			URL:          server.URL,
			SHA256:       hex.EncodeToString(digest[:]),
			Size:         int64(len(content)),
		}},
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err == nil || !strings.Contains(err.Error(), "input manifest changed") {
		t.Fatalf("EnsureWorkspace() error = %v, want immutable input error", err)
	}
	if _, exists := dataPlane.files["inputs/new.txt"]; exists {
		t.Fatal("changed input was materialized into an existing task workspace")
	}
}

func TestWorkspaceRuntimeStreamsInputLargerThanLegacyInlineLimit(t *testing.T) {
	content := bytes.Repeat([]byte("x"), maxInlineSandboxFileBytes+1)
	digest := sha256.Sum256(content)
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, _ *http.Request) {
		response.Header().Set("Content-Length", fmt.Sprint(len(content)))
		_, _ = response.Write(content)
	}))
	defer server.Close()

	provider := &fakeWorkspaceProvider{mount: &sandboxworkspace.Mount{
		WorkspaceID: "workspace-1", TaskID: "task-large", Root: WorkspaceRoot,
		Generation: 1, ManifestSHA256: strings.Repeat("a", 64), RevisionSHA256: strings.Repeat("b", 64),
		Hydration: workspace.Hydration{
			Generation: 1, ManifestSHA256: strings.Repeat("a", 64), RevisionSHA256: strings.Repeat("b", 64),
			Downloads: []workspace.Download{{RelativePath: "inputs/large.bin", URL: server.URL, SHA256: hex.EncodeToString(digest[:]), Size: int64(len(content))}},
		},
	}}
	dataPlane := &fakeWorkspaceRuntime{files: map[string][]byte{}}
	runtime, err := NewWorkspaceRuntime(dataPlane, provider)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-large"); err != nil {
		t.Fatal(err)
	}
	if got := len(dataPlane.files["inputs/large.bin"]); got != len(content) {
		t.Fatalf("materialized bytes = %d, want %d", got, len(content))
	}
}

type attachmentFixture struct {
	path    string
	content []byte
}

func (f attachmentFixture) digest() string {
	digest := sha256.Sum256(f.content)
	return hex.EncodeToString(digest[:])
}

func (f attachmentFixture) entry() workspace.Entry {
	return workspace.Entry{RelativePath: f.path, SHA256: f.digest(), Size: int64(len(f.content)), Mode: 0o600}
}

func inputMount(t *testing.T, server *httptest.Server, revision string, inputs ...attachmentFixture) *sandboxworkspace.Mount {
	t.Helper()
	downloads := make([]workspace.Download, 0, len(inputs))
	for _, input := range inputs {
		downloads = append(downloads, workspace.Download{
			RelativePath: input.path, URL: server.URL + "/" + input.path,
			SHA256: input.digest(), Size: int64(len(input.content)), Mode: 0o600,
		})
	}
	return &sandboxworkspace.Mount{
		WorkspaceID: "workspace-1", TaskID: "task-1", Root: WorkspaceRoot,
		Generation: 1, ManifestSHA256: strings.Repeat("c", 64), RevisionSHA256: revision,
		Hydration: workspace.Hydration{
			Generation: 1, ManifestSHA256: strings.Repeat("c", 64), RevisionSHA256: revision,
			Downloads: downloads,
		},
	}
}

func inputServer(t *testing.T, inputs ...attachmentFixture) *httptest.Server {
	t.Helper()
	bodies := make(map[string][]byte, len(inputs))
	for _, input := range inputs {
		bodies["/"+input.path] = input.content
	}
	server := httptest.NewServer(http.HandlerFunc(func(response http.ResponseWriter, request *http.Request) {
		body, ok := bodies[request.URL.Path]
		if !ok {
			response.WriteHeader(http.StatusNotFound)
			return
		}
		_, _ = response.Write(body)
	}))
	t.Cleanup(server.Close)
	return server
}

func TestEnsureWorkspaceHydrated_AdditiveAttachmentsHydrateInPlace(t *testing.T) {
	brief := attachmentFixture{path: "inputs/brief.txt", content: []byte("brief")}
	added := attachmentFixture{path: "inputs/attachments/contract.pdf", content: []byte("%PDF follow-up")}
	server := inputServer(t, brief, added)
	revisionX, revisionY := strings.Repeat("a", 64), strings.Repeat("b", 64)
	workspaces := &fakeWorkspaceProvider{mount: inputMount(t, server, revisionX, brief)}
	manager, provider := newTestManager(t)
	runtime, err := NewWorkspaceRuntime(manager, workspaces)
	if err != nil {
		t.Fatal(err)
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}

	workspaces.mount = inputMount(t, server, revisionY, brief, added)
	workspaces.additions = map[string][]workspace.Entry{revisionX + "->" + revisionY: {added.entry()}}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
		t.Fatalf("EnsureWorkspace() after an added attachment error = %v", err)
	}
	if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
		t.Fatalf("EnsureWorkspace() at the recorded revision error = %v", err)
	}

	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 1 {
		t.Fatalf("sandbox creates = %d, want the live sandbox reused", provider.creates)
	}
	if provider.puts != 2 {
		t.Fatalf("uploads = %d, want the original input once plus only the added attachment", provider.puts)
	}
	if got := string(provider.files[WorkspaceRoot+"/"+added.path]); got != string(added.content) {
		t.Fatalf("added attachment on sandbox disk = %q", got)
	}
	if fmt.Sprint(workspaces.additionCalls) != fmt.Sprint([]string{revisionX + "->" + revisionY}) {
		t.Fatalf("addition lookups = %v, want one X->Y lookup and revision Y recorded", workspaces.additionCalls)
	}
}

func TestEnsureWorkspaceHydrated_NonAdditiveDiffStillRefused(t *testing.T) {
	brief := attachmentFixture{path: "inputs/brief.txt", content: []byte("brief")}
	rewritten := attachmentFixture{path: "inputs/brief.txt", content: []byte("rewritten brief")}
	outside := attachmentFixture{path: "inputs/extra.txt", content: []byte("extra")}
	added := attachmentFixture{path: "inputs/attachments/contract.pdf", content: []byte("%PDF follow-up")}
	forged := attachmentFixture{path: added.path, content: []byte("not what was downloaded")}
	revisionX, revisionY := strings.Repeat("a", 64), strings.Repeat("b", 64)
	cases := []struct {
		name      string
		inputs    []attachmentFixture
		additions []workspace.Entry
	}{
		{name: "changed input refused by the data plane", inputs: []attachmentFixture{rewritten}},
		{name: "path outside attachments", inputs: []attachmentFixture{brief, outside}, additions: []workspace.Entry{outside.entry()}},
		{name: "nested attachment path", inputs: []attachmentFixture{brief, {path: "inputs/attachments/dir/c.pdf", content: []byte("c")}},
			additions: []workspace.Entry{{RelativePath: "inputs/attachments/dir/c.pdf", SHA256: attachmentFixture{content: []byte("c")}.digest(), Size: 1}}},
		{name: "addition absent from the hydration plan", inputs: []attachmentFixture{brief}, additions: []workspace.Entry{added.entry()}},
		{name: "addition digest differs from the plan", inputs: []attachmentFixture{brief, added}, additions: []workspace.Entry{forged.entry()}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			initial := inputServer(t, brief)
			next := inputServer(t, tc.inputs...)
			workspaces := &fakeWorkspaceProvider{mount: inputMount(t, initial, revisionX, brief)}
			manager, provider := newTestManager(t)
			runtime, err := NewWorkspaceRuntime(manager, workspaces)
			if err != nil {
				t.Fatal(err)
			}
			if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
				t.Fatal(err)
			}

			workspaces.mount = inputMount(t, next, revisionY, tc.inputs...)
			if tc.additions != nil {
				workspaces.additions = map[string][]workspace.Entry{revisionX + "->" + revisionY: tc.additions}
			}
			err = runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1")
			want := fmt.Sprintf("live sandbox is hydrated from revision %s and cannot be mutated to %s", revisionX, revisionY)
			if err == nil || !strings.HasPrefix(err.Error(), want) {
				t.Fatalf("EnsureWorkspace() error = %v, want refusal %q", err, want)
			}

			workspaces.mount = inputMount(t, initial, revisionX, brief)
			if err := runtime.EnsureWorkspace(context.Background(), "workspace-1", "task-1"); err != nil {
				t.Fatalf("refusal moved the recorded revision: %v", err)
			}
			provider.mu.Lock()
			defer provider.mu.Unlock()
			if provider.puts != 1 {
				t.Fatalf("uploads = %d, want only the original hydration", provider.puts)
			}
		})
	}
}
