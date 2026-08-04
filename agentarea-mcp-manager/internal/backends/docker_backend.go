package backends

import (
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/container"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

type dockerTaskRetirement struct {
	workspaceID string
	taskID      string
	ttl         time.Duration
	timer       *time.Timer
	deleting    bool
}

// DockerBackend implements the Backend interface using the existing container.Manager (Docker CLI)
type DockerBackend struct {
	manager             *container.Manager
	config              *config.Config
	logger              *slog.Logger
	retirementMu        sync.Mutex
	retirements         map[string]*dockerTaskRetirement
	activeOps           map[string]int
	hydrationRunMu      sync.Mutex
	hydrationMu         sync.Mutex
	hydrated            map[string]string
	executorIncarnation string
}

func (d *DockerBackend) RuntimeManifest(ctx context.Context) (*runtimeinfo.Manifest, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
	}
	return warmpool.GetRuntimeManifest(ctx, base, 10*time.Second)
}

// NewDockerBackend creates a new Docker backend
func NewDockerBackend(cfg *config.Config, logger *slog.Logger) *DockerBackend {
	manager := container.NewManager(cfg, logger)

	return &DockerBackend{
		manager:     manager,
		config:      cfg,
		logger:      logger,
		retirements: make(map[string]*dockerTaskRetirement),
		activeOps:   make(map[string]int),
		hydrated:    make(map[string]string),
	}
}

// EnsureWorkspaceHydrated coordinates the explicitly development-only shared
// executor within one manager process. Production runtimes use distributed
// Redis or Kubernetes control-plane state instead.
func (d *DockerBackend) EnsureWorkspaceHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
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
	if d.hydrated[key] != "" {
		d.hydrationMu.Unlock()
		return fmt.Errorf("live Docker development workspace revision cannot change")
	}
	d.hydrationMu.Unlock()
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

func (d *DockerBackend) observeExecutorIncarnation(ctx context.Context) (string, bool, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return "", false, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
	}
	incarnation, err := warmpool.GetExecutorIncarnation(ctx, base, 10*time.Second)
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

// GetManager returns the underlying container manager for backward compatibility
func (d *DockerBackend) GetManager() *container.Manager {
	return d.manager
}

// ExecuteSandbox runs a sandbox script against the configured sandbox-executor
// container (dev/compose data plane). The manager is the trusted control plane
// and never runs untrusted code itself — it delegates to the executor jail over
// HTTP. Implements sandboxrunner.SandboxExecutor.
func (d *DockerBackend) ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
	result, err := warmpool.PostExecute(ctx, base+"/execute", req, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

// SandboxFilePut writes a file into a task's sandbox workspace on the executor,
// the same filesystem ExecuteSandbox (bash) runs against. The control plane
// signs the ScopeFiles token; the executor secret never reaches the worker.
//
// TODO(prod-warm-pool): route per-task file requests to the same warm-pool pod
// that owns the task's exec session (sticky routing), so files land in the pod
// bash will actually run in. This dev path targets the single configured
// executor, matching ExecuteSandbox.
func (d *DockerBackend) SandboxFilePut(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
	result, err := warmpool.PutFile(ctx, base, req, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

func (d *DockerBackend) SandboxFileUpload(ctx context.Context, req sandboxruntime.FileUpload, content io.Reader) (*sandboxruntime.FileWriteResult, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
	result, err := warmpool.PutFileStream(ctx, base, warmpool.FileTransferRequest{
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
func (d *DockerBackend) SandboxFileGet(ctx context.Context, workspaceID, taskID, path string) (*warmpool.FileGetResponse, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
	result, err := warmpool.GetFileForIncarnation(ctx, base, workspaceID, taskID, path, incarnation, 30*time.Second)
	return result, mapDockerExecutorError(err)
}

func (d *DockerBackend) SandboxFileDownload(ctx context.Context, workspaceID, taskID, path string) (*sandboxruntime.FileDownload, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
	result, err := warmpool.OpenFileForIncarnation(ctx, base, workspaceID, taskID, path, incarnation, 10*time.Minute)
	if err != nil {
		finish()
		return nil, mapDockerExecutorError(err)
	}
	return &sandboxruntime.FileDownload{Content: &dockerOperationReadCloser{ReadCloser: result.Content, finish: finish}, Size: result.Size, Mode: fs.FileMode(result.Mode)}, nil
}

// SandboxFileList lists regular files under prefix in a task's sandbox workspace.
func (d *DockerBackend) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*warmpool.FileListResponse, error) {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if base == "" {
		return nil, fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
	result, err := warmpool.ListFilesForIncarnation(ctx, base, workspaceID, taskID, prefix, incarnation, 30*time.Second)
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
func (d *DockerBackend) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return err
	}
	if strings.TrimRight(d.config.Container.SandboxExecutorURL, "/") == "" {
		return fmt.Errorf("sandbox executor not configured (set SANDBOX_EXECUTOR_URL)")
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
func (d *DockerBackend) BeginOperation(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	release, err := d.beginTaskOperation(workspaceID, taskID)
	if err != nil {
		return nil, nil, err
	}
	return ctx, release, nil
}

func (d *DockerBackend) beginTaskOperation(workspaceID, taskID string) (func(), error) {
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

func (d *DockerBackend) endTaskOperation(workspaceID, taskID string) {
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

func (d *DockerBackend) armTaskRetirementLocked(record *dockerTaskRetirement, delay time.Duration) {
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

func (d *DockerBackend) finishTaskDeletion(record *dockerTaskRetirement, deletionErr error) {
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

func (d *DockerBackend) deleteTaskWorkspace(ctx context.Context, workspaceID, taskID string) error {
	base := strings.TrimRight(d.config.Container.SandboxExecutorURL, "/")
	if err := warmpool.DeleteTaskWorkspace(ctx, base, workspaceID, taskID, 30*time.Second); err != nil {
		return err
	}
	prefix := dockerTaskKey(workspaceID, taskID) + "\x00"
	d.hydrationMu.Lock()
	for key := range d.hydrated {
		if strings.HasPrefix(key, prefix) {
			delete(d.hydrated, key)
		}
	}
	d.hydrationMu.Unlock()
	return nil
}

func dockerTaskKey(workspaceID, taskID string) string {
	return workspaceID + "\x00" + taskID
}

// Initialize initializes the Docker backend
func (d *DockerBackend) Initialize(ctx context.Context) error {
	d.logger.Info("Initializing Docker backend")
	if os.Getenv("SANDBOX_SHARED_EXECUTOR_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT") != "true" {
		return fmt.Errorf("docker shared sandbox executor is development-only; set SANDBOX_SHARED_EXECUTOR_ALLOW_WEAK_ISOLATION_FOR_DEVELOPMENT=true explicitly")
	}
	return d.manager.Initialize(ctx)
}

// CreateInstance creates a new MCP server instance using the existing container manager
func (d *DockerBackend) CreateInstance(ctx context.Context, spec *InstanceSpec) (*InstanceResult, error) {
	d.logger.Info("Creating instance with Docker backend",
		slog.String("name", spec.Name),
		slog.String("image", spec.Image))

	// Convert InstanceSpec to models.CreateContainerRequest
	req, err := d.specToCreateRequest(spec)
	if err != nil {
		d.logger.Error("Failed to resolve instance isolation",
			slog.String("name", spec.Name),
			slog.String("error", err.Error()))
		return nil, err
	}

	// Use existing manager to create container
	container, err := d.manager.CreateContainer(ctx, req)
	if err != nil {
		d.logger.Error("Failed to create container via manager",
			slog.String("name", spec.Name),
			slog.String("error", err.Error()))
		return nil, fmt.Errorf("failed to create container: %w", err)
	}

	// Convert to InstanceResult
	result := &InstanceResult{
		ID:        container.ID,
		Name:      container.ServiceName,
		URL:       container.URL,
		Status:    string(container.Status),
		CreatedAt: container.CreatedAt,
	}

	d.logger.Info("Successfully created instance",
		slog.String("id", result.ID),
		slog.String("name", result.Name),
		slog.String("url", result.URL))

	return result, nil
}

// DeleteInstance removes an MCP server instance
func (d *DockerBackend) DeleteInstance(ctx context.Context, instanceID string) error {
	d.logger.Info("Deleting instance with Docker backend",
		slog.String("instance_id", instanceID))

	// Find container by ID or service name
	serviceName := d.findServiceNameByID(instanceID)
	if serviceName == "" {
		return fmt.Errorf("%w: %s", ErrInstanceNotFound, instanceID)
	}

	err := d.manager.DeleteContainer(ctx, serviceName)
	if err != nil {
		d.logger.Error("Failed to delete container",
			slog.String("instance_id", instanceID),
			slog.String("service_name", serviceName),
			slog.String("error", err.Error()))
		return fmt.Errorf("failed to delete container: %w", err)
	}

	d.logger.Info("Successfully deleted instance",
		slog.String("instance_id", instanceID),
		slog.String("service_name", serviceName))

	return nil
}

// GetInstanceStatus retrieves the current status of an instance
func (d *DockerBackend) GetInstanceStatus(ctx context.Context, instanceID string) (*InstanceStatus, error) {
	serviceName := d.findServiceNameByID(instanceID)
	if serviceName == "" {
		return nil, fmt.Errorf("%w: %s", ErrInstanceNotFound, instanceID)
	}

	container, err := d.manager.GetContainer(serviceName)
	if err != nil {
		return nil, fmt.Errorf("failed to get container: %w", err)
	}

	// Get real-time status
	status, err := d.manager.GetContainerStatus(ctx, serviceName)
	if err != nil {
		d.logger.Warn("Failed to get real-time status, using cached",
			slog.String("service_name", serviceName),
			slog.String("error", err.Error()))
		status = container.Status
	}

	// Get health check result
	var healthStatus *HealthCheckResult
	if healthResult, exists := d.manager.GetContainerHealthStatus(serviceName); exists {
		healthStatus = &HealthCheckResult{
			Healthy:       healthResult.Healthy,
			Status:        string(healthResult.Status),
			HTTPReachable: healthResult.HTTPReachable,
			ResponseTime:  healthResult.ResponseTime,
			ContainerID:   healthResult.ContainerID,
			ServiceName:   healthResult.ServiceName,
			Error:         healthResult.Error,
			Details:       healthResult.Details,
			Timestamp:     healthResult.Timestamp,
		}
	}

	instanceStatus := &InstanceStatus{
		ID:           container.ID,
		Name:         container.ServiceName,
		ServiceName:  container.ServiceName,
		Status:       string(status),
		URL:          container.URL,
		Image:        container.Image,
		Port:         container.Port,
		Environment:  container.Environment,
		Labels:       container.Labels,
		CreatedAt:    container.CreatedAt,
		UpdatedAt:    container.UpdatedAt,
		HealthStatus: healthStatus,
	}

	return instanceStatus, nil
}

// ListInstances returns all managed instances
func (d *DockerBackend) ListInstances(ctx context.Context) ([]*InstanceStatus, error) {
	containers := d.manager.ListContainers()
	instances := make([]*InstanceStatus, 0, len(containers))

	for _, container := range containers {
		// Get health status if available
		var healthStatus *HealthCheckResult
		if healthResult, exists := d.manager.GetContainerHealthStatus(container.ServiceName); exists {
			healthStatus = &HealthCheckResult{
				Healthy:       healthResult.Healthy,
				Status:        string(healthResult.Status),
				HTTPReachable: healthResult.HTTPReachable,
				ResponseTime:  healthResult.ResponseTime,
				ContainerID:   healthResult.ContainerID,
				ServiceName:   healthResult.ServiceName,
				Error:         healthResult.Error,
				Details:       healthResult.Details,
				Timestamp:     healthResult.Timestamp,
			}
		}

		instance := &InstanceStatus{
			ID:           container.ID,
			Name:         container.ServiceName,
			ServiceName:  container.ServiceName,
			Status:       string(container.Status),
			URL:          container.URL,
			Image:        container.Image,
			Port:         container.Port,
			Environment:  container.Environment,
			Labels:       container.Labels,
			CreatedAt:    container.CreatedAt,
			UpdatedAt:    container.UpdatedAt,
			HealthStatus: healthStatus,
		}

		instances = append(instances, instance)
	}

	return instances, nil
}

// UpdateInstance updates an existing instance configuration
func (d *DockerBackend) UpdateInstance(ctx context.Context, instanceID string, spec *InstanceSpec) error {
	d.logger.Info("Updating instance with Docker backend",
		slog.String("instance_id", instanceID))

	// For Docker backend, we need to recreate the container
	// First delete the existing instance
	if err := d.DeleteInstance(ctx, instanceID); err != nil {
		return fmt.Errorf("failed to delete existing instance: %w", err)
	}

	// Then create a new one with updated spec
	_, err := d.CreateInstance(ctx, spec)
	if err != nil {
		return fmt.Errorf("failed to recreate instance: %w", err)
	}

	return nil
}

// PerformHealthCheck performs health check on an instance
func (d *DockerBackend) PerformHealthCheck(ctx context.Context, instanceID string) (*HealthCheckResult, error) {
	serviceName := d.findServiceNameByID(instanceID)
	if serviceName == "" {
		return nil, fmt.Errorf("%w: %s", ErrInstanceNotFound, instanceID)
	}

	healthData, err := d.manager.PerformHealthCheck(ctx, serviceName)
	if err != nil {
		return nil, fmt.Errorf("health check failed: %w", err)
	}

	// Convert map to HealthCheckResult
	result := &HealthCheckResult{
		ServiceName: serviceName,
		Timestamp:   time.Now(),
	}

	if healthy, ok := healthData["healthy"].(bool); ok {
		result.Healthy = healthy
	}

	if status, ok := healthData["container_status"].(string); ok {
		result.Status = status
	}

	if reachable, ok := healthData["http_reachable"].(bool); ok {
		result.HTTPReachable = reachable
	}

	if responseTime, ok := healthData["response_time_ms"].(int64); ok {
		result.ResponseTime = time.Duration(responseTime) * time.Millisecond
	}

	if containerID, ok := healthData["container_id"].(string); ok {
		result.ContainerID = containerID
	}

	if errorMsg, ok := healthData["error"].(string); ok {
		result.Error = errorMsg
	}

	if details, ok := healthData["details"]; ok {
		result.Details = details
	}

	return result, nil
}

// Shutdown gracefully shuts down the Docker backend
func (d *DockerBackend) Shutdown(ctx context.Context) error {
	d.logger.Info("Shutting down Docker backend")
	d.retirementMu.Lock()
	for key, retirement := range d.retirements {
		retirement.timer.Stop()
		delete(d.retirements, key)
	}
	d.retirementMu.Unlock()
	return d.manager.Shutdown(ctx)
}

// Helper methods

// specToCreateRequest converts InstanceSpec to models.CreateContainerRequest
func (d *DockerBackend) specToCreateRequest(spec *InstanceSpec) (models.CreateContainerRequest, error) {
	req := models.CreateContainerRequest{
		ServiceName: spec.ServiceName,
		Image:       spec.Image,
		Port:        spec.Port,
		Environment: spec.Environment,
		Labels:      spec.Labels,
		Command:     spec.Command,
	}

	// Resolve the confinement for this workload. An MCP server is third-party
	// code, so the default is a confined tier, not the daemon's defaults.
	isolation, err := resolveSpecIsolation(spec, d.config.Container.DefaultIsolationTier)
	if err != nil {
		return models.CreateContainerRequest{}, err
	}
	req.Isolation = isolation

	// Add resource limits if specified
	if spec.Resources.Limits.Memory != "" {
		req.MemoryLimit = spec.Resources.Limits.Memory
	}
	if spec.Resources.Limits.CPU != "" {
		req.CPULimit = spec.Resources.Limits.CPU
	}

	// Add MCP-specific environment variables
	if req.Environment == nil {
		req.Environment = make(map[string]string)
	}
	req.Environment["MCP_INSTANCE_ID"] = spec.InstanceID
	req.Environment["MCP_SERVICE_NAME"] = spec.ServiceName
	req.Environment["MCP_CONTAINER_PORT"] = fmt.Sprintf("%d", spec.Port)

	return req, nil
}

// findServiceNameByID finds the service name by container ID or instance ID
func (d *DockerBackend) findServiceNameByID(instanceID string) string {
	containers := d.manager.ListContainers()

	for _, container := range containers {
		// Check if ID matches
		if container.ID == instanceID {
			return container.ServiceName
		}

		// Check if instance ID matches from environment
		if mcpInstanceID, exists := container.Environment["MCP_INSTANCE_ID"]; exists {
			if mcpInstanceID == instanceID {
				return container.ServiceName
			}
		}

		// Check if service name matches directly
		if container.ServiceName == instanceID {
			return container.ServiceName
		}
	}

	return ""
}
