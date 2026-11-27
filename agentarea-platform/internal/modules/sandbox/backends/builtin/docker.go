package builtin

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/sandboxruntime"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/warmpool"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/backends/workspace"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/sandbox/supervisor/runtimeinfo"
)

type dockerTaskRetirement struct {
	workspaceID string
	taskID      string
	ttl         time.Duration
	timer       *time.Timer
	deleting    bool
}

// Docker is the development sandbox on the shared executor container
// (AGENTAREA_SANDBOX_EXECUTOR_URL): weak isolation, refused unless
// AGENTAREA_SANDBOX_ALLOW_WEAK_ISOLATION=true.
type Docker struct {
	executorURL         string
	allowWeakIsolation  bool
	executor            warmpool.Executor
	logger              *slog.Logger
	retirementMu        sync.Mutex
	retirements         map[string]*dockerTaskRetirement
	activeOps           map[string]int
	hydrationRunMu      sync.Mutex
	hydrationMu         sync.Mutex
	hydrated            map[string]string
	executorIncarnation string
}

// NewDocker is the shared-executor sandbox at executorURL; allowWeakIsolation
// is AGENTAREA_SANDBOX_ALLOW_WEAK_ISOLATION=true.
func NewDocker(executorURL string, allowWeakIsolation bool, executor warmpool.Executor, logger *slog.Logger) *Docker {
	return &Docker{
		executorURL:        executorURL,
		allowWeakIsolation: allowWeakIsolation,
		executor:           executor,
		logger:             logger,
		retirements:        make(map[string]*dockerTaskRetirement),
		activeOps:          make(map[string]int),
		hydrated:           make(map[string]string),
	}
}

// sharedExecutorBase resolves the endpoint of the shared sandbox executor.
//
// That executor is a single long-lived container serving every task, so it is
// weak isolation and has to be asked for explicitly. The refusal used to sit in
// Initialize, which also gated MCP container lifecycle -- the part of this
// backend that has nothing to do with sandboxes -- so a host serving only MCP
// refused to start at all. Sandbox callers hit it here instead, where the
// weak-isolation decision actually applies.
func (d *Docker) sharedExecutorBase() (string, error) {
	if !d.allowWeakIsolation {
		return "", fmt.Errorf("docker shared sandbox executor is development-only; set AGENTAREA_SANDBOX_ALLOW_WEAK_ISOLATION=true explicitly")
	}
	base := strings.TrimRight(d.executorURL, "/")
	if base == "" {
		return "", fmt.Errorf("sandbox executor not configured (set AGENTAREA_SANDBOX_EXECUTOR_URL)")
	}
	return base, nil
}

func (d *Docker) RuntimeManifest(ctx context.Context) (*runtimeinfo.Manifest, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	return d.executor.GetRuntimeManifest(ctx, base, 10*time.Second)
}

// EnsureWorkspaceHydrated coordinates the explicitly development-only shared
// executor within one manager process. Production runtimes use distributed
// Redis or Kubernetes control-plane state instead.
func (d *Docker) EnsureWorkspaceHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
	advance func(context.Context, string) error,
) error {
	d.hydrationRunMu.Lock()
	defer d.hydrationRunMu.Unlock()
	incarnation, _, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return err
	}
	key := dockerTaskKey(workspaceID, taskID)
	d.hydrationMu.Lock()
	if d.hydrated[key] == revision {
		d.hydrationMu.Unlock()
		return nil
	}
	from := d.hydrated[key]
	d.hydrationMu.Unlock()
	if from != "" {
		if advance == nil {
			return fmt.Errorf("live Docker development workspace is hydrated from revision %s and cannot move to %s", from, revision)
		}
		if err := advance(ctx, from); err != nil {
			return fmt.Errorf("live Docker development workspace is hydrated from revision %s and cannot move to %s: %w", from, revision, err)
		}
		d.hydrationMu.Lock()
		d.hydrated[key] = revision
		d.hydrationMu.Unlock()
		return nil
	}
	if err := hydrate(ctx); err != nil {
		return err
	}
	after, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return err
	}
	if changed || after != incarnation {
		return sandboxruntime.ErrWorkspaceRehydration
	}
	d.hydrationMu.Lock()
	d.hydrated[key] = revision
	d.hydrationMu.Unlock()
	return nil
}

func (d *Docker) observeExecutorIncarnation(ctx context.Context) (string, bool, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return "", false, err
	}
	incarnation, err := d.executor.GetExecutorIncarnation(ctx, base, 10*time.Second)
	if err != nil {
		return "", false, err
	}
	d.hydrationMu.Lock()
	defer d.hydrationMu.Unlock()
	changed := d.executorIncarnation != "" && d.executorIncarnation != incarnation
	if changed {
		clear(d.hydrated)
	}
	d.executorIncarnation = incarnation
	return incarnation, changed, nil
}

// ExecuteSandbox runs a sandbox script against the configured sandbox-executor
// container (dev/compose data plane). The manager is the trusted control plane
// and never runs untrusted code itself — it delegates to the executor jail over
// HTTP. Implements sandboxrunner.SandboxExecutor.
func (d *Docker) ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	incarnation, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return nil, err
	} else if changed {
		return nil, sandboxruntime.ErrWorkspaceRehydration
	}
	req.ExecutorIncarnation = incarnation
	finish, err := d.beginTaskOperation(req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer finish()
	result, err := d.executor.PostExecute(ctx, base+"/execute", req, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

// SandboxFilePut writes a file into a task's sandbox workspace on the executor,
// the same filesystem ExecuteSandbox (bash) runs against. The control plane
// signs the ScopeFiles token; the executor secret never reaches the worker.
//
// The Docker backend has one shared executor, so every task's files and bash
// meet there; the Kubernetes backend routes both to the task's own pod.
func (d *Docker) SandboxFilePut(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	incarnation, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return nil, err
	} else if changed {
		return nil, sandboxruntime.ErrWorkspaceRehydration
	}
	req.ExecutorIncarnation = incarnation
	finish, err := d.beginTaskOperation(req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer finish()
	result, err := d.executor.PutFile(ctx, base, req, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

func (d *Docker) SandboxFileUpload(ctx context.Context, req sandboxruntime.FileUpload, content io.Reader) (*sandboxruntime.FileWriteResult, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	incarnation, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return nil, err
	} else if changed {
		return nil, sandboxruntime.ErrWorkspaceRehydration
	}
	finish, err := d.beginTaskOperation(req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer finish()
	result, err := d.executor.PutFileStream(ctx, base, warmpool.FileTransferRequest{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
		ExecutorIncarnation: incarnation,
		Path:                req.Path, Size: req.Size, SHA256: req.SHA256, Mode: uint32(req.Mode),
	}, content, 10*time.Minute)
	if err != nil {
		return nil, mapDockerExecutorError(err)
	}
	return &sandboxruntime.FileWriteResult{Path: result.Path, Size: result.Size}, nil
}

// SandboxFileGet reads a file from a task's sandbox workspace on the executor.
func (d *Docker) SandboxFileGet(ctx context.Context, workspaceID, taskID, path string) (*warmpool.FileGetResponse, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	incarnation, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return nil, err
	}
	if changed {
		return nil, sandboxruntime.ErrWorkspaceRehydration
	}
	finish, err := d.beginTaskOperation(workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	defer finish()
	result, err := d.executor.GetFileForIncarnation(ctx, base, workspaceID, taskID, path, incarnation, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

func (d *Docker) SandboxFileDownload(ctx context.Context, workspaceID, taskID, path string) (*sandboxruntime.FileDownload, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	incarnation, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return nil, err
	}
	if changed {
		return nil, sandboxruntime.ErrWorkspaceRehydration
	}
	finish, err := d.beginTaskOperation(workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	result, err := d.executor.OpenFileForIncarnation(ctx, base, workspaceID, taskID, path, incarnation, 10*time.Minute)
	if err != nil {
		finish()
		return nil, mapDockerExecutorError(err)
	}
	return &sandboxruntime.FileDownload{Content: &dockerOperationReadCloser{ReadCloser: result.Content, finish: finish}, Size: result.Size, Mode: fs.FileMode(result.Mode)}, nil
}

// SandboxFileList lists regular files under prefix in a task's sandbox workspace.
func (d *Docker) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*warmpool.FileListResponse, error) {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return nil, err
	}
	incarnation, changed, err := d.observeExecutorIncarnation(ctx)
	if err != nil {
		return nil, err
	}
	if changed {
		return nil, sandboxruntime.ErrWorkspaceRehydration
	}
	finish, err := d.beginTaskOperation(workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	defer finish()
	result, err := d.executor.ListFilesForIncarnation(ctx, base, workspaceID, taskID, prefix, incarnation, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

func mapDockerExecutorError(err error) error {
	if errors.Is(err, warmpool.ErrExecutorIncarnationChanged) || errors.Is(err, warmpool.ErrExecutorUnsafe) {
		return sandboxruntime.ErrWorkspaceRehydration
	}
	return err
}

// RetireSandboxTask keeps the Docker development workspace inspectable for
// idleTTL, then deletes that exact workspace/task directory from the shared
// executor. Any file or execution demand during the grace period renews it.
func (d *Docker) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return err
	}
	if strings.TrimRight(d.executorURL, "/") == "" {
		return fmt.Errorf("sandbox executor not configured (set AGENTAREA_SANDBOX_EXECUTOR_URL)")
	}
	key := dockerTaskKey(workspaceID, taskID)
	d.retirementMu.Lock()
	existing := d.retirements[key]
	if existing != nil {
		if existing.timer != nil {
			existing.timer.Stop()
		}
		delete(d.retirements, key)
	}
	if idleTTL > 0 {
		record := &dockerTaskRetirement{workspaceID: workspaceID, taskID: taskID, ttl: idleTTL}
		d.retirements[key] = record
		if d.activeOps[key] == 0 {
			d.armTaskRetirementLocked(record, idleTTL)
		}
		d.retirementMu.Unlock()
		return nil
	}
	if d.activeOps[key] > 0 {
		if existing != nil {
			d.retirements[key] = existing
		}
		d.retirementMu.Unlock()
		return fmt.Errorf("sandbox task has active operations and cannot be force-retired")
	}
	record := &dockerTaskRetirement{workspaceID: workspaceID, taskID: taskID, deleting: true}
	d.retirements[key] = record
	d.retirementMu.Unlock()
	err := d.deleteTaskWorkspace(ctx, workspaceID, taskID)
	d.finishTaskDeletion(record, err)
	return err
}

// BeginOperation lets a composing layer hold one retirement fence across a
// multi-step operation. The underlying counter is a reference count, so nesting
// is safe and the count only drops to zero once the whole composite is done —
// which is what keeps a force-retire from landing between hydration and
// execution.
func (d *Docker) BeginOperation(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	release, err := d.beginTaskOperation(workspaceID, taskID)
	if err != nil {
		return nil, nil, err
	}
	return ctx, release, nil
}

func (d *Docker) beginTaskOperation(workspaceID, taskID string) (func(), error) {
	key := dockerTaskKey(workspaceID, taskID)
	d.retirementMu.Lock()
	if retirement := d.retirements[key]; retirement != nil {
		if retirement.deleting {
			d.retirementMu.Unlock()
			return nil, fmt.Errorf("sandbox task workspace is being retired")
		}
		if retirement.timer != nil {
			retirement.timer.Stop()
			retirement.timer = nil
		}
	}
	d.activeOps[key]++
	d.retirementMu.Unlock()
	var once sync.Once
	return func() {
		once.Do(func() { d.endTaskOperation(workspaceID, taskID) })
	}, nil
}

func (d *Docker) endTaskOperation(workspaceID, taskID string) {
	key := dockerTaskKey(workspaceID, taskID)
	d.retirementMu.Lock()
	if d.activeOps[key] > 1 {
		d.activeOps[key]--
		d.retirementMu.Unlock()
		return
	}
	delete(d.activeOps, key)
	if record := d.retirements[key]; record != nil && !record.deleting && record.timer == nil {
		d.armTaskRetirementLocked(record, record.ttl)
	}
	d.retirementMu.Unlock()
}

func (d *Docker) armTaskRetirementLocked(record *dockerTaskRetirement, delay time.Duration) {
	key := dockerTaskKey(record.workspaceID, record.taskID)
	record.timer = time.AfterFunc(delay, func() {
		d.retirementMu.Lock()
		if d.retirements[key] != record || record.deleting {
			d.retirementMu.Unlock()
			return
		}
		record.timer = nil
		if d.activeOps[key] > 0 {
			d.retirementMu.Unlock()
			return
		}
		record.deleting = true
		d.retirementMu.Unlock()
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		err := d.deleteTaskWorkspace(ctx, record.workspaceID, record.taskID)
		cancel()
		if err != nil {
			d.logger.Error("Failed to retire Docker task workspace", "workspace_id", record.workspaceID, "task_id", record.taskID, "error", err)
			retryDelay := time.Minute
			if record.ttl < retryDelay {
				retryDelay = record.ttl
			}
			if retryDelay <= 0 {
				retryDelay = time.Second
			}
			d.retirementMu.Lock()
			if d.retirements[key] == record {
				record.deleting = false
				d.armTaskRetirementLocked(record, retryDelay)
			}
			d.retirementMu.Unlock()
			return
		}
		d.finishTaskDeletion(record, nil)
	})
}

func (d *Docker) finishTaskDeletion(record *dockerTaskRetirement, deletionErr error) {
	key := dockerTaskKey(record.workspaceID, record.taskID)
	d.retirementMu.Lock()
	defer d.retirementMu.Unlock()
	if d.retirements[key] != record {
		return
	}
	if deletionErr == nil {
		delete(d.retirements, key)
		return
	}
	record.deleting = false
}

type dockerOperationReadCloser struct {
	io.ReadCloser
	finish func()
	once   sync.Once
}

func (r *dockerOperationReadCloser) Read(buffer []byte) (int, error) {
	n, err := r.ReadCloser.Read(buffer)
	if err != nil {
		r.once.Do(r.finish)
	}
	return n, err
}

func (r *dockerOperationReadCloser) Close() error {
	err := r.ReadCloser.Close()
	r.once.Do(r.finish)
	return err
}

func (d *Docker) deleteTaskWorkspace(ctx context.Context, workspaceID, taskID string) error {
	base, err := d.sharedExecutorBase()
	if err != nil {
		return err
	}
	if err := d.executor.DeleteTaskWorkspace(ctx, base, workspaceID, taskID, 30*time.Second); err != nil {
		return err
	}
	d.hydrationMu.Lock()
	delete(d.hydrated, dockerTaskKey(workspaceID, taskID))
	d.hydrationMu.Unlock()
	return nil
}

func dockerTaskKey(workspaceID, taskID string) string {
	return workspaceID + "\x00" + taskID
}

// Initialize initializes the Docker backend
