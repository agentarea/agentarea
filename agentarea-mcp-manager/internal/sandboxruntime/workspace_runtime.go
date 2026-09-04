package sandboxruntime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/sandboxworkspace"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

type WorkspaceFileDemand struct {
	WorkspaceID string
	TaskID      string
	Ensure      bool
}

type WorkspaceFileRead struct {
	WorkspaceFileDemand
	Path string
}

type WorkspaceFileList struct {
	WorkspaceFileDemand
	Prefix string
}

// WorkspaceFileReader owns the complete on-demand read use case. Callers never
// coordinate the retirement fence and hydration protocol themselves.
type WorkspaceFileReader interface {
	GetWorkspaceFile(context.Context, WorkspaceFileRead) (*sandboxcontract.FileGetResponse, error)
	OpenWorkspaceFile(context.Context, WorkspaceFileRead) (*FileDownload, error)
	ListWorkspaceFiles(context.Context, WorkspaceFileList) (*sandboxcontract.FileListResponse, error)
}

// WorkspaceFileWriter owns the complete on-demand write use cases. The method
// names are intentionally distinct from provider primitives so a raw runtime
// cannot be wired into the HTTP layer without the workspace decorator.
type WorkspaceFileWriter interface {
	PutWorkspaceFile(context.Context, sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error)
	UploadWorkspaceFile(context.Context, FileUpload, io.Reader) (*FileWriteResult, error)
}

// WorkspaceRuntime composes compute and workspace data planes. Python only
// sends workspace/task identity; all copy-in decisions
// and provider-specific materialization happen here in Go.
type WorkspaceRuntime struct {
	base       ManagedRuntime
	workspaces sandboxworkspace.Ensurer
	httpClient *http.Client
}

func NewWorkspaceRuntime(base ManagedRuntime, workspaces sandboxworkspace.Ensurer) (*WorkspaceRuntime, error) {
	if base == nil {
		return nil, fmt.Errorf("sandbox runtime is required")
	}
	if workspaces == nil {
		return nil, fmt.Errorf("workspace provider is required")
	}
	return &WorkspaceRuntime{
		base:       base,
		workspaces: workspaces,
		httpClient: &http.Client{Timeout: 10 * time.Minute},
	}, nil
}

// WorkspaceProvider names the workspace data plane. It is resolved once by the
// composition root (see LoadWorkspaceProviderFromEnv) and passed in as an
// already-resolved dependency, so the decorator never reads process state.
type WorkspaceProvider string

const WorkspaceProviderS3 WorkspaceProvider = "s3"

// NewWorkspaceRuntimeForProvider requires an explicit workspace provider. A
// missing provider is a deployment error: silently running without inputs or
// durability would weaken the task contract.
func NewWorkspaceRuntimeForProvider(
	ctx context.Context,
	base ManagedRuntime,
	provider WorkspaceProvider,
	cfg workspace.RepositoryConfig,
) (ComposedRuntime, error) {
	switch provider {
	case WorkspaceProviderS3:
		workspaces, err := sandboxworkspace.NewS3ProviderFromConfig(ctx, cfg)
		if err != nil {
			return nil, fmt.Errorf("configure S3 workspace provider: %w", err)
		}
		wrapped, err := NewWorkspaceRuntime(base, workspaces)
		if err != nil {
			return nil, err
		}
		if lister, ok := base.(SandboxLister); ok {
			return &workspaceRuntimeWithInventory{WorkspaceRuntime: wrapped, lister: lister}, nil
		}
		return wrapped, nil
	default:
		return nil, fmt.Errorf("unsupported sandbox workspace provider %q; supported value: s3", provider)
	}
}

// BeginOperation delegates the fence so this decorator's own composite
// operations and the base runtime share one retirement boundary.
func (r *WorkspaceRuntime) BeginOperation(
	ctx context.Context,
	workspaceID, taskID string,
) (context.Context, func(), error) {
	return r.base.BeginOperation(ctx, workspaceID, taskID)
}

// ExecuteSandbox hydrates and then executes under a single fence. Hydration and
// execution must not be separately fenced: retirement landing between them would
// destroy the hydrated binding and the command would run in a fresh, empty one.
func (r *WorkspaceRuntime) ExecuteSandbox(ctx context.Context, req sandboxcontract.ExecuteRequest) (*sandboxcontract.ExecuteResponse, error) {
	ctx, release, err := r.base.BeginOperation(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer release()
	if err := r.EnsureWorkspace(ctx, req.WorkspaceID, req.TaskID); err != nil {
		return nil, err
	}
	return r.base.ExecuteSandbox(ctx, req)
}

func (r *WorkspaceRuntime) SandboxFilePut(ctx context.Context, req sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	return r.PutWorkspaceFile(ctx, req)
}

func (r *WorkspaceRuntime) PutWorkspaceFile(ctx context.Context, req sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	ctx, release, err := r.base.BeginOperation(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer release()
	if err := r.EnsureWorkspace(ctx, req.WorkspaceID, req.TaskID); err != nil {
		return nil, err
	}
	return r.base.SandboxFilePut(ctx, req)
}

func (r *WorkspaceRuntime) SandboxFileUpload(ctx context.Context, req FileUpload, content io.Reader) (*FileWriteResult, error) {
	return r.UploadWorkspaceFile(ctx, req, content)
}

func (r *WorkspaceRuntime) UploadWorkspaceFile(ctx context.Context, req FileUpload, content io.Reader) (*FileWriteResult, error) {
	mode, err := normalizeFileMode(req.Mode)
	if err != nil {
		return nil, err
	}
	req.Mode = mode
	ctx, release, err := r.base.BeginOperation(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer release()
	if err := r.EnsureWorkspace(ctx, req.WorkspaceID, req.TaskID); err != nil {
		return nil, err
	}
	return r.base.SandboxFileUpload(ctx, req, content)
}

func (r *WorkspaceRuntime) SandboxFileGet(ctx context.Context, workspaceID, taskID, path string) (*sandboxcontract.FileGetResponse, error) {
	return r.base.SandboxFileGet(ctx, workspaceID, taskID, path)
}

func (r *WorkspaceRuntime) SandboxFileDownload(ctx context.Context, workspaceID, taskID, path string) (*FileDownload, error) {
	return r.base.SandboxFileDownload(ctx, workspaceID, taskID, path)
}

func (r *WorkspaceRuntime) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*sandboxcontract.FileListResponse, error) {
	return r.base.SandboxFileList(ctx, workspaceID, taskID, prefix)
}

func (r *WorkspaceRuntime) GetWorkspaceFile(ctx context.Context, req WorkspaceFileRead) (*sandboxcontract.FileGetResponse, error) {
	operationCtx, release, err := r.beginWorkspaceFileDemand(ctx, req.WorkspaceFileDemand)
	if err != nil {
		return nil, err
	}
	defer release()
	return r.base.SandboxFileGet(operationCtx, req.WorkspaceID, req.TaskID, req.Path)
}

func (r *WorkspaceRuntime) OpenWorkspaceFile(ctx context.Context, req WorkspaceFileRead) (*FileDownload, error) {
	operationCtx, release, err := r.beginWorkspaceFileDemand(ctx, req.WorkspaceFileDemand)
	if err != nil {
		return nil, err
	}
	download, err := r.base.SandboxFileDownload(operationCtx, req.WorkspaceID, req.TaskID, req.Path)
	if err != nil {
		release()
		return nil, err
	}
	download.Content = &workspaceDemandReadCloser{source: download.Content, release: release}
	return download, nil
}

func (r *WorkspaceRuntime) ListWorkspaceFiles(ctx context.Context, req WorkspaceFileList) (*sandboxcontract.FileListResponse, error) {
	operationCtx, release, err := r.beginWorkspaceFileDemand(ctx, req.WorkspaceFileDemand)
	if err != nil {
		return nil, err
	}
	defer release()
	return r.base.SandboxFileList(operationCtx, req.WorkspaceID, req.TaskID, req.Prefix)
}

func (r *WorkspaceRuntime) beginWorkspaceFileDemand(
	ctx context.Context,
	demand WorkspaceFileDemand,
) (context.Context, func(), error) {
	if err := workspace.ValidateIdentifier("workspace_id", demand.WorkspaceID); err != nil {
		return nil, nil, err
	}
	if err := workspace.ValidateIdentifier("task_id", demand.TaskID); err != nil {
		return nil, nil, err
	}
	operationCtx, release, err := r.base.BeginOperation(ctx, demand.WorkspaceID, demand.TaskID)
	if err != nil {
		return nil, nil, err
	}
	if demand.Ensure {
		if err := r.EnsureWorkspace(operationCtx, demand.WorkspaceID, demand.TaskID); err != nil {
			release()
			return nil, nil, err
		}
	}
	return operationCtx, release, nil
}

type workspaceDemandReadCloser struct {
	source  io.ReadCloser
	release func()
	once    sync.Once
}

func (r *workspaceDemandReadCloser) Read(buffer []byte) (int, error) {
	return r.source.Read(buffer)
}

func (r *workspaceDemandReadCloser) Close() error {
	err := r.source.Close()
	r.once.Do(r.release)
	return err
}

func (r *WorkspaceRuntime) RuntimeManifest(ctx context.Context) (*runtimeinfo.Manifest, error) {
	return r.base.RuntimeManifest(ctx)
}

func (r *WorkspaceRuntime) EnsureWorkspaceHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
) error {
	return r.base.EnsureWorkspaceHydrated(ctx, workspaceID, taskID, revision, hydrate)
}

func (r *WorkspaceRuntime) EnsureWorkspace(ctx context.Context, workspaceID, taskID string) error {
	if workspaceID == "" || taskID == "" {
		return fmt.Errorf("workspace_id and task_id are required")
	}
	mount, err := r.workspaces.Ensure(ctx, workspaceID, taskID)
	if err != nil {
		return fmt.Errorf("ensure task workspace: %w", err)
	}
	if mount == nil || mount.WorkspaceID != workspaceID || mount.TaskID != taskID || mount.Root != WorkspaceRoot {
		return fmt.Errorf("workspace provider returned an invalid mount identity")
	}
	if mount.Generation != mount.Hydration.Generation ||
		mount.ManifestSHA256 != mount.Hydration.ManifestSHA256 ||
		mount.RevisionSHA256 != mount.Hydration.RevisionSHA256 {
		return fmt.Errorf("workspace provider returned inconsistent manifest identity")
	}
	if mount.Generation < 0 ||
		(mount.Generation == 0 && (mount.ManifestSHA256 != "" || len(mount.Hydration.Downloads) != 0)) ||
		(mount.Generation > 0 && !validSHA256(mount.ManifestSHA256)) {
		return fmt.Errorf("workspace provider returned an invalid manifest checksum")
	}
	if !validSHA256(mount.RevisionSHA256) {
		return fmt.Errorf("workspace provider returned an invalid hydration revision")
	}
	return r.base.EnsureWorkspaceHydrated(ctx, workspaceID, taskID, mount.RevisionSHA256, func(hydrationCtx context.Context) error {
		return r.materializeInputs(hydrationCtx, workspaceID, taskID, mount)
	})
}

func (r *WorkspaceRuntime) materializeInputs(ctx context.Context, workspaceID, taskID string, mount *sandboxworkspace.Mount) error {
	for _, input := range mount.Hydration.Downloads {
		normalized, normalizeErr := workspace.NormalizeRelativePath(input.RelativePath)
		if normalizeErr != nil || normalized != input.RelativePath || !strings.HasPrefix(normalized, "inputs/") {
			return fmt.Errorf("workspace provider attempted to hydrate non-input path %q", input.RelativePath)
		}
		content, downloadErr := r.openInput(ctx, input)
		if downloadErr != nil {
			return fmt.Errorf("materialize workspace input %q: %w", input.RelativePath, downloadErr)
		}
		hasher := sha256.New()
		verified := &countingReader{reader: io.TeeReader(io.LimitReader(content, input.Size+1), hasher)}
		mode, modeErr := normalizeFileMode(fs.FileMode(input.Mode))
		if modeErr != nil {
			content.Close()
			return fmt.Errorf("materialize workspace input %q mode: %w", input.RelativePath, modeErr)
		}
		_, putErr := r.base.SandboxFileUpload(ctx, FileUpload{
			WorkspaceID: workspaceID,
			TaskID:      taskID,
			Path:        input.RelativePath,
			Size:        input.Size,
			SHA256:      input.SHA256,
			Mode:        mode,
		}, verified)
		delivered := verified.count
		extra := []byte{0}
		extraBytes := 0
		if putErr == nil && delivered == input.Size {
			extraBytes, _ = verified.Read(extra)
		}
		closeErr := content.Close()
		if putErr != nil {
			return fmt.Errorf("materialize workspace input %q: %w", input.RelativePath, putErr)
		}
		if delivered != input.Size || extraBytes != 0 || hex.EncodeToString(hasher.Sum(nil)) != input.SHA256 {
			return fmt.Errorf("materialize workspace input %q: size or checksum mismatch", input.RelativePath)
		}
		if closeErr != nil {
			return fmt.Errorf("close workspace input %q: %w", input.RelativePath, closeErr)
		}
	}
	return nil
}

func validSHA256(value string) bool {
	if len(value) != sha256.Size*2 {
		return false
	}
	_, err := hex.DecodeString(value)
	return err == nil && value == strings.ToLower(value)
}

func (r *WorkspaceRuntime) openInput(ctx context.Context, input workspace.Download) (io.ReadCloser, error) {
	if input.Size < 0 {
		return nil, fmt.Errorf("input size %d is invalid", input.Size)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, input.URL, nil)
	if err != nil {
		return nil, err
	}
	for name, value := range input.Headers {
		if name != "Host" {
			request.Header.Set(name, value)
		}
	}
	response, err := r.httpClient.Do(request)
	if err != nil {
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		response.Body.Close()
		return nil, fmt.Errorf("input download returned HTTP %d", response.StatusCode)
	}
	if response.ContentLength >= 0 && response.ContentLength != input.Size {
		response.Body.Close()
		return nil, fmt.Errorf("input Content-Length mismatch: got %d, expected %d", response.ContentLength, input.Size)
	}
	return response.Body, nil
}

func (r *WorkspaceRuntime) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	return r.base.RetireSandboxTask(ctx, workspaceID, taskID, idleTTL)
}

type workspaceRuntimeWithInventory struct {
	*WorkspaceRuntime
	lister SandboxLister
}

func (r *workspaceRuntimeWithInventory) ListSandboxes(ctx context.Context, workspaceID string) ([]SandboxStatus, error) {
	return r.lister.ListSandboxes(ctx, workspaceID)
}

var _ Runtime = (*WorkspaceRuntime)(nil)
var _ ManagedRuntime = (*WorkspaceRuntime)(nil)
var _ WorkspaceFileReader = (*WorkspaceRuntime)(nil)
var _ ComposedRuntime = (*WorkspaceRuntime)(nil)
var _ TaskRetirer = (*WorkspaceRuntime)(nil)
var _ SandboxLister = (*workspaceRuntimeWithInventory)(nil)
