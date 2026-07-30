package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"sort"
	"strings"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

type OpenSandboxConfig struct {
	Connection       opensandbox.ConnectionConfig
	Images           map[string]string
	Entrypoint       []string
	ResourceCPU      string
	ResourceMemory   string
	LeaseTTL         time.Duration
	Isolation        string
	AllowWeakDev     bool
	AllowInsecure    bool
	SecureAccess     *bool
	EgressMode       string
	PersistWorkspace bool
	VolumePrefix     string
}

type OpenSandboxProvider struct {
	cfg OpenSandboxConfig
}

func NewOpenSandboxProvider(cfg OpenSandboxConfig) (*OpenSandboxProvider, error) {
	domain := strings.TrimSpace(cfg.Connection.Domain)
	if domain == "" {
		return nil, fmt.Errorf("OpenSandbox domain is required")
	}
	endpoint, err := url.Parse(domain)
	if err != nil || endpoint.Scheme == "" || endpoint.Host == "" {
		return nil, fmt.Errorf("OpenSandbox domain must be an absolute URL")
	}
	if endpoint.Scheme != "https" && !(endpoint.Scheme == "http" && cfg.AllowInsecure) {
		return nil, fmt.Errorf("OpenSandbox domain must use HTTPS unless insecure development mode is explicitly enabled")
	}
	if cfg.LeaseTTL <= 0 {
		return nil, fmt.Errorf("OpenSandbox task lease TTL must be positive")
	}
	secureAccess := true
	if cfg.SecureAccess != nil {
		secureAccess = *cfg.SecureAccess
	}
	if !secureAccess && !cfg.Connection.UseServerProxy {
		return nil, fmt.Errorf("OpenSandbox secureAccess=false requires server proxy routing")
	}
	cfg.SecureAccess = &secureAccess
	cfg.Isolation = strings.ToLower(strings.TrimSpace(cfg.Isolation))
	switch cfg.Isolation {
	case "gvisor", "kata", "firecracker":
	case "container-dev":
		if !cfg.AllowWeakDev {
			return nil, fmt.Errorf("OpenSandbox isolation=container-dev requires explicit weak-isolation development opt-in")
		}
	default:
		return nil, fmt.Errorf("OpenSandbox isolation must be one of gvisor, kata, firecracker, or container-dev")
	}
	if cfg.ResourceCPU == "" {
		cfg.ResourceCPU = "500m"
	}
	if cfg.ResourceMemory == "" {
		cfg.ResourceMemory = "512Mi"
	}
	cfg.EgressMode = strings.ToLower(strings.TrimSpace(cfg.EgressMode))
	switch cfg.EgressMode {
	case "provider":
		if cfg.Isolation == "gvisor" {
			return nil, fmt.Errorf("OpenSandbox provider network policy is incompatible with gVisor; configure an audited host-public egress policy")
		}
	case "host-public":
		if cfg.Isolation != "gvisor" {
			return nil, fmt.Errorf("OpenSandbox egress mode host-public is only supported by the dedicated gVisor host profile")
		}
	default:
		return nil, fmt.Errorf("OpenSandbox egress mode must be provider or host-public")
	}
	if cfg.PersistWorkspace && strings.TrimSpace(cfg.VolumePrefix) == "" {
		cfg.VolumePrefix = "agentarea-task"
	}
	return &OpenSandboxProvider{cfg: cfg}, nil
}

func (p *OpenSandboxProvider) Name() string { return "opensandbox" }

func (p *OpenSandboxProvider) Create(ctx context.Context, req CreateRequest) (*Session, error) {
	image := p.cfg.Images[req.PackageInstall]
	if image == "" {
		return nil, fmt.Errorf("OpenSandbox image for package_install=%s is not configured", req.PackageInstall)
	}
	if p.cfg.EgressMode == "host-public" && req.PackageInstall != runtimeinfo.PackageInstallAllowed {
		return nil, fmt.Errorf(
			"OpenSandbox gVisor host profile cannot enforce package_install=%s egress; refusing weaker isolation",
			req.PackageInstall,
		)
	}
	ttlSeconds := int(p.cfg.LeaseTTL.Seconds())
	var networkPolicy *opensandbox.NetworkPolicy
	if p.cfg.EgressMode == "provider" {
		networkPolicy = openSandboxNetworkPolicy(req.PackageInstall)
	}
	var volumes []opensandbox.Volume
	if p.cfg.PersistWorkspace {
		createVolume := true
		deleteVolume := false
		volumes = []opensandbox.Volume{{
			Name: "workspace",
			PVC: &opensandbox.PVC{
				ClaimName:                  taskVolumeName(p.cfg.VolumePrefix, req.WorkspaceID, req.TaskID),
				CreateIfNotExists:          &createVolume,
				DeleteOnSandboxTermination: &deleteVolume,
			},
			MountPath: WorkspaceRoot,
		}}
	}
	sandbox, err := opensandbox.CreateSandbox(ctx, p.cfg.Connection, opensandbox.SandboxCreateOptions{
		Image:          image,
		Entrypoint:     p.cfg.Entrypoint,
		TimeoutSeconds: &ttlSeconds,
		SecureAccess:   *p.cfg.SecureAccess,
		NetworkPolicy:  networkPolicy,
		Volumes:        volumes,
		ResourceLimits: opensandbox.ResourceLimits{
			"cpu":    p.cfg.ResourceCPU,
			"memory": p.cfg.ResourceMemory,
		},
		Metadata: map[string]string{
			"agentarea.workspace_id":    req.WorkspaceID,
			"agentarea.task_id":         req.TaskID,
			"agentarea.package_install": req.PackageInstall,
			"agentarea.isolation":       p.cfg.Isolation,
			"agentarea.resource_cpu":    p.cfg.ResourceCPU,
			"agentarea.resource_memory": p.cfg.ResourceMemory,
			"agentarea.egress_mode":     p.cfg.EgressMode,
		},
	})
	if err != nil {
		return nil, err
	}
	session := &Session{ID: sandbox.ID()}
	session.Data = map[string]string{
		"isolation": p.cfg.Isolation,
		"cpu":       p.cfg.ResourceCPU,
		"memory":    p.cfg.ResourceMemory,
	}
	execution, err := sandbox.RunCommandWithOpts(ctx, opensandbox.RunCommandRequest{
		Command: "mkdir -p -- " + shellQuote(WorkspaceRoot),
		Cwd:     "/",
		Timeout: 30_000,
	}, nil)
	if err != nil || execution.ExitCode == nil || *execution.ExitCode != 0 {
		_ = mapOpenSandboxError(sandbox.Kill(context.Background()))
		if err != nil {
			return nil, fmt.Errorf("initialize OpenSandbox workspace: %w", mapOpenSandboxError(err))
		}
		return nil, fmt.Errorf("initialize OpenSandbox workspace: command exited without success")
	}
	return session, nil
}

func (p *OpenSandboxProvider) Renew(ctx context.Context, session *Session, ttl time.Duration) error {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return err
	}
	if _, err := sandbox.Renew(ctx, ttl); err != nil {
		return mapOpenSandboxError(err)
	}
	return nil
}

func (p *OpenSandboxProvider) Execute(ctx context.Context, session *Session, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return nil, err
	}
	timeout := req.TimeoutSeconds
	if timeout <= 0 {
		timeout = 120
	}
	stdoutLimit, err := outputCaptureLimit(req.StdoutMaxBytes)
	if err != nil {
		return nil, err
	}
	stderrLimit, err := outputCaptureLimit(req.StderrMaxBytes)
	if err != nil {
		return nil, err
	}
	stdout := newBoundedOutput(stdoutLimit)
	stderr := newBoundedOutput(stderrLimit)
	started := time.Now()
	execution, err := sandbox.RunCommandWithOpts(ctx, opensandbox.RunCommandRequest{
		Command: req.CommandBody,
		Cwd:     WorkspaceRoot,
		Timeout: int64(timeout * 1000),
	}, &opensandbox.ExecutionHandlers{
		SkipAccumulation: true,
		OnStdout: func(message opensandbox.OutputMessage) error {
			stdout.WriteMessage(message.Text)
			return nil
		},
		OnStderr: func(message opensandbox.OutputMessage) error {
			stderr.WriteMessage(message.Text)
			return nil
		},
	})
	if err != nil {
		return nil, mapOpenSandboxError(err)
	}

	result := &warmpool.ExecuteResponse{ExecutionTimeMs: time.Since(started).Milliseconds()}
	if execution.Complete != nil && execution.Complete.ExecutionTime > 0 {
		result.ExecutionTimeMs = execution.Complete.ExecutionTime
	}
	if execution.ExitCode != nil {
		result.ExitCode = *execution.ExitCode
	}
	result.Stdout = stdout.String()
	result.Stderr = stderr.String()
	result.StdoutTruncated = stdout.Truncated()
	result.StderrTruncated = stderr.Truncated()
	if execution.Error != nil && result.Stderr == "" {
		result.Stderr = execution.Error.Name + ": " + execution.Error.Value
		result.Stderr, result.StderrTruncated = truncateOutput(result.Stderr, stderrLimit)
		if result.ExitCode == 0 {
			result.ExitCode = 1
		}
	}
	result.Artifacts, err = p.artifacts(ctx, sandbox, req.ArtifactPaths)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (p *OpenSandboxProvider) PutFile(ctx context.Context, session *Session, remotePath string, content []byte) error {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return err
	}
	return mapOpenSandboxError(sandbox.UploadFile(ctx, bytes.NewReader(content), opensandbox.UploadFileOptions{
		FileName: path.Base(remotePath),
		Metadata: opensandbox.FileMetadata{Path: remotePath},
	}))
}

func (p *OpenSandboxProvider) GetFile(ctx context.Context, session *Session, remotePath string) ([]byte, error) {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return nil, err
	}
	reader, err := sandbox.DownloadFile(ctx, remotePath, "")
	if err != nil {
		var apiErr *opensandbox.APIError
		if errors.As(err, &apiErr) && apiErr.StatusCode == http.StatusNotFound {
			return nil, fmt.Errorf("%w: %v", ErrFileNotFound, err)
		}
		return nil, mapOpenSandboxError(err)
	}
	defer reader.Close()
	content, err := io.ReadAll(io.LimitReader(reader, 16*1024*1024+1))
	if err != nil {
		return nil, fmt.Errorf("read OpenSandbox file: %w", err)
	}
	if len(content) > 16*1024*1024 {
		return nil, fmt.Errorf("sandbox file exceeds 16 MiB response limit")
	}
	return content, nil
}

func (p *OpenSandboxProvider) ListFiles(ctx context.Context, session *Session, remotePrefix string) ([]string, error) {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return nil, err
	}
	files, err := sandbox.ListDirectoryWithDepth(ctx, remotePrefix, 64)
	if err != nil {
		return nil, mapOpenSandboxError(err)
	}
	result := make([]string, 0, len(files))
	for _, file := range files {
		if file.Type == "file" || file.Type == "" {
			result = append(result, file.Path)
		}
	}
	sort.Strings(result)
	return result, nil
}

func (p *OpenSandboxProvider) Delete(ctx context.Context, session *Session) error {
	sandbox, err := opensandbox.ConnectSandbox(ctx, p.cfg.Connection, session.ID)
	if err != nil {
		return mapOpenSandboxError(err)
	}
	return mapOpenSandboxError(sandbox.Kill(ctx))
}

func (p *OpenSandboxProvider) List(ctx context.Context, workspaceID string) ([]SandboxStatus, error) {
	if workspaceID == "" {
		return nil, fmt.Errorf("workspace_id is required")
	}
	manager := opensandbox.NewSandboxManager(p.cfg.Connection)
	result := make([]SandboxStatus, 0)
	for page := 1; ; page++ {
		response, err := manager.ListSandboxInfos(ctx, opensandbox.ListOptions{
			Metadata: map[string]string{"agentarea.workspace_id": workspaceID},
			Page:     page,
			PageSize: 100,
		})
		if err != nil {
			return nil, mapOpenSandboxError(err)
		}
		for _, info := range response.Items {
			if info.Status.State == opensandbox.StateTerminated {
				continue
			}
			metadata := info.Metadata
			result = append(result, SandboxStatus{
				ID:             info.ID,
				Provider:       p.Name(),
				WorkspaceID:    workspaceID,
				TaskID:         metadata["agentarea.task_id"],
				PackageInstall: metadata["agentarea.package_install"],
				State:          strings.ToLower(string(info.Status.State)),
				CreatedAt:      info.CreatedAt,
				ExpiresAt:      info.ExpiresAt,
				Resources: map[string]string{
					"cpu":    valueOrDefault(metadata["agentarea.resource_cpu"], p.cfg.ResourceCPU),
					"memory": valueOrDefault(metadata["agentarea.resource_memory"], p.cfg.ResourceMemory),
				},
				Isolation: valueOrDefault(metadata["agentarea.isolation"], p.cfg.Isolation),
			})
		}
		if !response.Pagination.HasNextPage {
			break
		}
	}
	sort.Slice(result, func(i, j int) bool {
		return result[i].CreatedAt.After(result[j].CreatedAt)
	})
	return result, nil
}

func (p *OpenSandboxProvider) connect(ctx context.Context, session *Session) (*opensandbox.Sandbox, error) {
	sandbox, err := opensandbox.ConnectSandbox(ctx, p.cfg.Connection, session.ID)
	if err != nil {
		return nil, mapOpenSandboxError(err)
	}
	return sandbox, nil
}

func (p *OpenSandboxProvider) artifacts(ctx context.Context, sandbox *opensandbox.Sandbox, paths []string) ([]warmpool.SandboxArtifact, error) {
	artifacts := make([]warmpool.SandboxArtifact, 0, len(paths))
	for _, requested := range paths {
		remotePath, err := sandboxPath(requested)
		if err != nil {
			return nil, err
		}
		info, err := sandbox.GetFileInfo(ctx, remotePath)
		if err != nil {
			artifacts = append(artifacts, warmpool.SandboxArtifact{Path: requested, Error: mapOpenSandboxError(err).Error()})
			continue
		}
		file, ok := info[remotePath]
		if !ok && len(info) == 1 {
			for _, candidate := range info {
				file = candidate
			}
		}
		artifacts = append(artifacts, warmpool.SandboxArtifact{
			Path: requested,
			Name: path.Base(requested),
			Size: file.Size,
		})
	}
	return artifacts, nil
}

func mapOpenSandboxError(err error) error {
	if err == nil {
		return nil
	}
	var apiErr *opensandbox.APIError
	if errors.As(err, &apiErr) {
		if apiErr.StatusCode == http.StatusNotFound {
			return fmt.Errorf("%w: %v", ErrSessionNotFound, err)
		}
	}
	return err
}

func valueOrDefault(value, fallback string) string {
	if value != "" {
		return value
	}
	return fallback
}

func taskVolumeName(prefix, workspaceID, taskID string) string {
	digest := sha256.Sum256([]byte(workspaceID + "\x00" + taskID))
	return fmt.Sprintf("%s-%x", strings.TrimSuffix(prefix, "-"), digest[:12])
}

func openSandboxNetworkPolicy(packageInstall string) *opensandbox.NetworkPolicy {
	defaultAction := "deny"
	if packageInstall == runtimeinfo.PackageInstallAllowed {
		defaultAction = "allow"
	}
	return &opensandbox.NetworkPolicy{DefaultAction: defaultAction}
}

func truncateOutput(value string, limit int64) (string, bool) {
	if int64(len(value)) <= limit {
		return value, false
	}
	return value[:limit], true
}
