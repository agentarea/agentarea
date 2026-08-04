package sandboxruntime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"

	opensandbox "github.com/alibaba/OpenSandbox/sdks/sandbox/go"
	"github.com/google/uuid"

	"github.com/agentarea/mcp-manager/internal/execsupervisor"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

type OpenSandboxConfig struct {
	Connection          opensandbox.ConnectionConfig
	Image               string
	Entrypoint          []string
	ResourceCPU         string
	ResourceMemory      string
	ResourceStorage     string
	LeaseTTL            time.Duration
	Isolation           string
	RuntimeIdentity     string
	AllowWeakDev        bool
	AllowInsecure       bool
	SecureAccess        *bool
	EgressMode          string
	AllowInternetAccess bool
	PersistWorkspace    bool
	VolumePrefix        string
}

type OpenSandboxProvider struct {
	cfg OpenSandboxConfig
}

const maxOpenSandboxInventoryPages = 10_000

const maxOpenSandboxInspectionBytes = 64 * 1024

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
	if cfg.Connection.Protocol != "" && cfg.Connection.Protocol != endpoint.Scheme {
		return nil, fmt.Errorf(
			"OpenSandbox protocol %q does not match domain scheme %q",
			cfg.Connection.Protocol,
			endpoint.Scheme,
		)
	}
	// Server-proxy endpoints are intentionally returned without a scheme.
	// The SDK uses Connection.Protocol to restore it, so it must match the
	// lifecycle endpoint. Otherwise an HTTPS deployment is contacted over HTTP
	// and a 301 redirect rewrites streaming POST requests such as /command to GET.
	cfg.Connection.Protocol = endpoint.Scheme
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
	cfg.RuntimeIdentity = strings.TrimSpace(cfg.RuntimeIdentity)
	switch cfg.Isolation {
	case "gvisor":
		if cfg.RuntimeIdentity == "" {
			return nil, fmt.Errorf("OpenSandbox gVisor runtime identity is required")
		}
		if cfg.Image != "" && !immutableOCIImage(cfg.Image) {
			return nil, fmt.Errorf("OpenSandbox image must use an immutable digest for strong isolation")
		}
	case "kata", "firecracker":
		return nil, fmt.Errorf("OpenSandbox isolation=%s is not supported until the provider exposes a verifiable runtime attestation", cfg.Isolation)
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
	if cfg.ResourceStorage == "" {
		return nil, fmt.Errorf("OpenSandbox ephemeral storage limit is required")
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
		if !cfg.AllowInternetAccess {
			return nil, fmt.Errorf("OpenSandbox egress mode host-public requires deployment-level internet access")
		}
	default:
		return nil, fmt.Errorf("OpenSandbox egress mode must be provider or host-public")
	}
	if cfg.PersistWorkspace && strings.TrimSpace(cfg.VolumePrefix) == "" {
		cfg.VolumePrefix = "agentarea-task"
	}
	if cfg.PersistWorkspace {
		return nil, fmt.Errorf("OpenSandbox persistent workspaces are disabled until archive/delete lifecycle and GC are configured")
	}
	return &OpenSandboxProvider{cfg: cfg}, nil
}

func (p *OpenSandboxProvider) Name() string { return "opensandbox" }

func (p *OpenSandboxProvider) ProvisioningTimeout() time.Duration {
	return p.cfg.Connection.RequestTimeout
}

func (p *OpenSandboxProvider) Create(ctx context.Context, req CreateRequest) (*Session, error) {
	if req.ProvisioningID == "" {
		return nil, fmt.Errorf("OpenSandbox provisioning identity is required")
	}
	image := p.cfg.Image
	if image == "" {
		return nil, fmt.Errorf("OpenSandbox image is not configured")
	}
	ttlSeconds := int(p.cfg.LeaseTTL.Seconds())
	var networkPolicy *opensandbox.NetworkPolicy
	if p.cfg.EgressMode == "provider" {
		networkPolicy = openSandboxNetworkPolicy(p.cfg.AllowInternetAccess)
	}
	_, imageDigest, _ := strings.Cut(image, "@sha256:")
	metadata := map[string]string{
		"agentarea.provisioning_id":  req.ProvisioningID,
		"agentarea.workspace_id":     req.WorkspaceID,
		"agentarea.task_id":          req.TaskID,
		"agentarea.isolation":        p.cfg.Isolation,
		"agentarea.runtime_identity": p.cfg.RuntimeIdentity,
		"agentarea.resource_cpu":     p.cfg.ResourceCPU,
		"agentarea.resource_memory":  p.cfg.ResourceMemory,
		"agentarea.resource_storage": p.cfg.ResourceStorage,
		"agentarea.egress_mode":      p.cfg.EgressMode,
	}
	if len(imageDigest) == 64 {
		metadata["agentarea.image_digest_0"] = imageDigest[:32]
		metadata["agentarea.image_digest_1"] = imageDigest[32:]
	}
	// A lifecycle create is not idempotent. Keep retries enabled for read and
	// maintenance calls, but issue exactly one POST for this durable provisioning
	// identity. An ambiguous response is reconciled by the Manager from metadata;
	// an SDK retry could allocate two sandboxes before reconciliation starts.
	createConnection := p.cfg.Connection
	createConnection.Retry = nil
	sandbox, err := opensandbox.CreateSandbox(ctx, createConnection, opensandbox.SandboxCreateOptions{
		Image:          image,
		Entrypoint:     p.cfg.Entrypoint,
		TimeoutSeconds: &ttlSeconds,
		SecureAccess:   *p.cfg.SecureAccess,
		NetworkPolicy:  networkPolicy,
		ResourceLimits: opensandbox.ResourceLimits{
			"cpu":    p.cfg.ResourceCPU,
			"memory": p.cfg.ResourceMemory,
			"disk":   p.cfg.ResourceStorage,
		},
		Metadata: metadata,
	})
	if err != nil {
		return nil, err
	}
	session := &Session{ID: sandbox.ID()}
	session.Data = map[string]string{
		"isolation":        p.cfg.Isolation,
		"runtime_identity": p.cfg.RuntimeIdentity,
		"image":            image,
		"cpu":              p.cfg.ResourceCPU,
		"memory":           p.cfg.ResourceMemory,
		"storage":          p.cfg.ResourceStorage,
	}
	// The one-shot connection above is scoped to the non-idempotent create.
	// Reconnect by the returned identity so safe GET/exec/file operations retain
	// the configured retry policy without ever replaying the allocation POST.
	sandbox, err = opensandbox.ConnectSandbox(ctx, p.cfg.Connection, session.ID)
	if err != nil {
		return session, fmt.Errorf("connect provisioned OpenSandbox sandbox: %w", mapOpenSandboxError(err))
	}
	if err := p.verifyCreatedSandbox(ctx, sandbox, image, metadata); err != nil {
		return session, err
	}
	if err := p.verifyExecutionSupervisor(ctx, sandbox, req.Supervisor); err != nil {
		return session, err
	}
	if err := sandbox.CreateDirectory(ctx, WorkspaceRoot, 700); err != nil {
		return session, fmt.Errorf("initialize OpenSandbox workspace: %w", mapOpenSandboxError(err))
	}
	if _, err := p.AuditWorkspace(ctx, session); err != nil {
		return session, fmt.Errorf("verify OpenSandbox workspace accounting: %w", err)
	}
	return session, nil
}

func (p *OpenSandboxProvider) ResolveProvisioning(
	ctx context.Context,
	intent ProvisioningIntent,
) ([]*Session, error) {
	if err := intent.validate(p.Name()); err != nil {
		return nil, err
	}
	manager := opensandbox.NewSandboxManager(p.cfg.Connection)
	result := make([]*Session, 0, 1)
	for page := 1; page <= maxOpenSandboxInventoryPages; page++ {
		response, err := manager.ListSandboxInfos(ctx, opensandbox.ListOptions{
			Metadata: map[string]string{"agentarea.provisioning_id": intent.ProvisioningID},
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
			expected := map[string]string{
				"agentarea.provisioning_id": intent.ProvisioningID,
				"agentarea.workspace_id":    intent.WorkspaceID,
				"agentarea.task_id":         intent.TaskID,
			}
			for name, value := range expected {
				if info.Metadata[name] != value {
					return nil, fmt.Errorf("OpenSandbox provisioning match %s has inconsistent %s", info.ID, name)
				}
			}
			if info.ID == "" {
				return nil, fmt.Errorf("OpenSandbox provisioning inventory returned an empty sandbox identity")
			}
			result = append(result, &Session{ID: info.ID})
		}
		if !response.Pagination.HasNextPage {
			return result, nil
		}
	}
	return nil, fmt.Errorf("OpenSandbox provisioning inventory exceeded %d pages", maxOpenSandboxInventoryPages)
}

func (p *OpenSandboxProvider) verifyCreatedSandbox(
	ctx context.Context,
	sandbox *opensandbox.Sandbox,
	image string,
	metadata map[string]string,
) error {
	info, err := opensandbox.NewSandboxManager(p.cfg.Connection).GetSandboxInfo(ctx, sandbox.ID())
	if err != nil {
		return fmt.Errorf("verify OpenSandbox control-plane binding: %w", mapOpenSandboxError(err))
	}
	if info == nil || info.ID != sandbox.ID() {
		return fmt.Errorf("OpenSandbox control plane returned an inconsistent sandbox identity")
	}
	if info.Image == nil {
		return fmt.Errorf("OpenSandbox control plane did not report the bound image")
	}
	if !sameImmutableOCIImage(info.Image.URI, image) {
		expectedRepository, _, expectedOK := parseImmutableOCIImage(image)
		actualRepository, actualIsTag := parseTaggedOCIRepository(info.Image.URI)
		if !expectedOK || !actualIsTag || actualRepository != expectedRepository {
			return fmt.Errorf("OpenSandbox control plane bound image %q, expected %q", info.Image.URI, image)
		}
		inspectedImage, inspectErr := p.inspectSandboxImage(ctx, sandbox.ID())
		if inspectErr != nil {
			return fmt.Errorf("attest OpenSandbox host image: %w", inspectErr)
		}
		if !sameImmutableOCIImage(inspectedImage, image) {
			return fmt.Errorf("OpenSandbox host bound image %q, expected %q", inspectedImage, image)
		}
	}
	for key, expected := range metadata {
		if info.Metadata[key] != expected {
			return fmt.Errorf("OpenSandbox control plane returned inconsistent %s metadata", key)
		}
	}
	if p.cfg.Isolation != "gvisor" {
		return nil
	}
	probe := newBoundedOutput(64 * 1024)
	execution, err := sandbox.RunCommandWithOpts(ctx, opensandbox.RunCommandRequest{
		Command: "/bin/cat -- /proc/version",
		Cwd:     "/",
		Timeout: 10_000,
	}, &opensandbox.ExecutionHandlers{
		SkipAccumulation: true,
		OnStdout: func(message opensandbox.OutputMessage) error {
			probe.WriteMessage(message.Text)
			return nil
		},
	})
	if err != nil {
		return fmt.Errorf("probe OpenSandbox gVisor runtime: %w", mapOpenSandboxError(err))
	}
	if execution.ExitCode == nil || *execution.ExitCode != 0 || probe.Truncated() || !strings.Contains(strings.ToLower(probe.String()), "gvisor") {
		return fmt.Errorf("OpenSandbox data plane did not prove the required gVisor runtime")
	}
	return nil
}

// inspectSandboxImage reads the Docker engine's container configuration through
// the OpenSandbox host diagnostics API. Docker-backed OpenSandbox v0.2.2 loses
// the digest in SandboxInfo by rendering the first image tag. Config.Image still
// contains the immutable reference passed to the engine, so a tag readback is
// accepted only when this independent host-side view matches exactly. The
// deprecated text endpoint is deliberately a fail-closed compatibility adapter:
// any response drift makes provisioning fail until the adapter is updated.
func (p *OpenSandboxProvider) inspectSandboxImage(ctx context.Context, sandboxID string) (string, error) {
	endpoint := p.cfg.Connection.GetBaseURL() + "/v1/sandboxes/" + url.PathEscape(sandboxID) + "/diagnostics/inspect"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return "", fmt.Errorf("build diagnostics request: %w", err)
	}
	for key, value := range p.cfg.Connection.Headers {
		req.Header.Set(key, value)
	}
	if apiKey := p.cfg.Connection.GetAPIKey(); apiKey != "" {
		req.Header.Set(p.cfg.Connection.GetAuthHeader(), apiKey)
	}
	req.Header.Set("Accept", "text/plain")

	client := openSandboxHTTPClient(p.cfg.Connection)
	response, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("request diagnostics: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return "", fmt.Errorf("diagnostics returned HTTP %d", response.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(response.Body, maxOpenSandboxInspectionBytes+1))
	if err != nil {
		return "", fmt.Errorf("read diagnostics: %w", err)
	}
	if len(body) > maxOpenSandboxInspectionBytes {
		return "", fmt.Errorf("diagnostics response exceeds %d bytes", maxOpenSandboxInspectionBytes)
	}
	return parseOpenSandboxInspectedImage(string(body))
}

func openSandboxHTTPClient(cfg opensandbox.ConnectionConfig) *http.Client {
	var client http.Client
	if cfg.HTTPClient != nil {
		client = *cfg.HTTPClient
	} else {
		client.Transport = opensandbox.DefaultTransport()
		if cfg.Transport != nil {
			client.Transport = cfg.Transport.NewTransport()
		}
	}
	client.Timeout = cfg.GetRequestTimeout()
	client.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return http.ErrUseLastResponse
	}
	return &client
}

func parseOpenSandboxInspectedImage(body string) (string, error) {
	var image string
	for _, line := range strings.Split(body, "\n") {
		if !strings.HasPrefix(line, "Image:") {
			continue
		}
		if image != "" {
			return "", fmt.Errorf("diagnostics returned multiple image identities")
		}
		image = strings.TrimSpace(strings.TrimPrefix(line, "Image:"))
	}
	if image == "" {
		return "", fmt.Errorf("diagnostics did not report an image identity")
	}
	return image, nil
}

func sameImmutableOCIImage(actual, expected string) bool {
	actualRepository, actualDigest, actualOK := parseImmutableOCIImage(actual)
	expectedRepository, expectedDigest, expectedOK := parseImmutableOCIImage(expected)
	return actualOK && expectedOK && actualRepository == expectedRepository && actualDigest == expectedDigest
}

func parseTaggedOCIRepository(image string) (string, bool) {
	image = strings.TrimSpace(image)
	if image == "" || strings.Contains(image, "@") {
		return "", false
	}
	lastSlash := strings.LastIndexByte(image, '/')
	lastColon := strings.LastIndexByte(image, ':')
	if lastColon > lastSlash {
		image = image[:lastColon]
	}
	return image, image != ""
}

func parseImmutableOCIImage(image string) (string, string, bool) {
	repository, digest, ok := strings.Cut(strings.TrimSpace(image), "@sha256:")
	if !ok || repository == "" || len(digest) != 64 || strings.Contains(repository, "@") {
		return "", "", false
	}
	if _, err := hex.DecodeString(digest); err != nil {
		return "", "", false
	}
	return repository, strings.ToLower(digest), true
}

func immutableOCIImage(image string) bool {
	_, digest, ok := strings.Cut(image, "@sha256:")
	if !ok || len(digest) != 64 {
		return false
	}
	_, err := hex.DecodeString(digest)
	return err == nil
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

func (p *OpenSandboxProvider) ExecuteQuiescent(ctx context.Context, session *Session, executionRequest QuiescentExecution) (*sandboxcontract.ExecuteResponse, error) {
	timeout, err := executionRequest.validate()
	if err != nil {
		return nil, err
	}
	req := executionRequest.Request
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return nil, err
	}
	if err := p.verifyExecutionSupervisor(ctx, sandbox, executionRequest.Supervisor); err != nil {
		return nil, err
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
	statusPath, err := execsupervisor.StatusPath(uuid.NewString())
	if err != nil {
		return nil, err
	}
	command, err := execsupervisor.Invocation(
		executionRequest.Supervisor,
		statusPath,
		timeout,
		executionRequest.MaxFileBytes,
		req.CommandBody,
	)
	if err != nil {
		return nil, err
	}
	rootUID, rootGID := int32(0), int32(0)
	started := time.Now()
	providerExecution, err := sandbox.RunCommandWithOpts(ctx, opensandbox.RunCommandRequest{
		Command: command,
		Cwd:     WorkspaceRoot,
		Timeout: int64((timeout + supervisorCleanupGraceSeconds) * 1000),
		UID:     &rootUID,
		GID:     &rootGID,
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
	if providerExecution.ExitCode == nil || *providerExecution.ExitCode != 0 || providerExecution.Error != nil {
		return nil, fmt.Errorf("OpenSandbox execution supervisor did not complete cleanly")
	}
	statusCtx, cancelStatus := context.WithTimeout(context.WithoutCancel(ctx), providerCleanupTimeout)
	status, statusErr := p.readExecutionStatus(statusCtx, sandbox, statusPath, executionRequest.Supervisor)
	cleanupErr := mapOpenSandboxError(sandbox.DeleteFiles(statusCtx, []string{statusPath}))
	cancelStatus()
	if cleanupErr != nil && !errors.Is(cleanupErr, ErrFileNotFound) {
		cleanupErr = fmt.Errorf("delete OpenSandbox execution status: %w", cleanupErr)
	} else {
		cleanupErr = nil
	}
	if statusErr != nil || cleanupErr != nil {
		return nil, errors.Join(statusErr, cleanupErr)
	}

	result := &sandboxcontract.ExecuteResponse{ExecutionTimeMs: time.Since(started).Milliseconds()}
	if providerExecution.Complete != nil && providerExecution.Complete.ExecutionTime > 0 {
		result.ExecutionTimeMs = providerExecution.Complete.ExecutionTime
	}
	result.ExitCode = status.ChildExitCode
	result.Stdout = stdout.String()
	result.Stderr = stderr.String()
	result.StdoutTruncated = stdout.Truncated()
	result.StderrTruncated = stderr.Truncated()
	result.Artifacts, err = p.artifacts(ctx, sandbox, req.ArtifactPaths)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (p *OpenSandboxProvider) verifyExecutionSupervisor(
	ctx context.Context,
	sandbox *opensandbox.Sandbox,
	expected execsupervisor.Attestation,
) error {
	if err := expected.Validate(); err != nil {
		return err
	}
	info, err := sandbox.GetFileInfo(ctx, expected.Path)
	if err != nil {
		return fmt.Errorf("inspect OpenSandbox execution supervisor: %w", mapOpenSandboxError(err))
	}
	file, ok := openSandboxFileInfo(info, expected.Path)
	if !ok || file.Type != "file" || file.Size <= 0 || file.Size > execsupervisor.MaxBinaryBytes {
		return fmt.Errorf("OpenSandbox execution supervisor metadata is invalid")
	}
	mode, err := openSandboxModeFromAPI(file.Mode)
	if err != nil || file.Owner != "root" || file.Group != "root" || mode.Perm()&0o022 != 0 || mode.Perm()&0o100 == 0 {
		return fmt.Errorf("OpenSandbox execution supervisor must be root-owned, executable, and not group/other writable")
	}
	reader, err := sandbox.DownloadFile(ctx, expected.Path, "")
	if err != nil {
		return fmt.Errorf("download OpenSandbox execution supervisor: %w", mapOpenSandboxError(err))
	}
	return verifySupervisorDownload(&FileDownload{Content: reader, Size: file.Size, Mode: mode}, expected)
}

func (p *OpenSandboxProvider) readExecutionStatus(
	ctx context.Context,
	sandbox *opensandbox.Sandbox,
	statusPath string,
	expected execsupervisor.Attestation,
) (execsupervisor.Status, error) {
	info, err := sandbox.GetFileInfo(ctx, statusPath)
	if err != nil {
		return execsupervisor.Status{}, fmt.Errorf("inspect OpenSandbox execution status: %w", mapOpenSandboxError(err))
	}
	file, ok := openSandboxFileInfo(info, statusPath)
	if !ok || file.Type != "file" || file.Owner != "root" || file.Group != "root" || file.Mode != 600 {
		return execsupervisor.Status{}, fmt.Errorf("OpenSandbox execution status is not a root-owned 0600 file")
	}
	reader, err := sandbox.DownloadFile(ctx, statusPath, "")
	if err != nil {
		return execsupervisor.Status{}, fmt.Errorf("download OpenSandbox execution status: %w", mapOpenSandboxError(err))
	}
	return decodeSupervisorStatusDownload(&FileDownload{Content: reader, Size: file.Size, Mode: 0o600}, expected)
}

func openSandboxFileInfo(files map[string]opensandbox.FileInfo, requested string) (opensandbox.FileInfo, bool) {
	file, ok := files[requested]
	if !ok && len(files) == 1 {
		for _, candidate := range files {
			file, ok = candidate, true
		}
	}
	return file, ok
}

func (p *OpenSandboxProvider) PutFile(ctx context.Context, session *Session, transfer FileUpload, content io.Reader) error {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return err
	}
	apiMode, err := openSandboxModeToAPI(transfer.Mode)
	if err != nil {
		return err
	}
	tempPath, err := stagingPath(transfer.Path)
	if err != nil {
		return err
	}
	if err := mapOpenSandboxError(sandbox.UploadFile(ctx, content, opensandbox.UploadFileOptions{
		FileName: path.Base(tempPath),
		Metadata: opensandbox.FileMetadata{Path: tempPath, Mode: apiMode},
	})); err != nil {
		return err
	}
	if err := p.verifyOpenSandboxUpload(ctx, sandbox, tempPath, transfer); err != nil {
		return p.cleanupOpenSandboxStaging(tempPath, sandbox, err)
	}
	if err := sandbox.MoveFiles(ctx, opensandbox.MoveRequest{{Src: tempPath, Dest: transfer.Path}}); err != nil {
		return p.cleanupOpenSandboxStaging(
			tempPath,
			sandbox,
			fmt.Errorf("atomic OpenSandbox file commit: %w", mapOpenSandboxError(err)),
		)
	}
	return nil
}

func (p *OpenSandboxProvider) verifyOpenSandboxUpload(
	ctx context.Context,
	sandbox *opensandbox.Sandbox,
	tempPath string,
	transfer FileUpload,
) error {
	info, err := sandbox.GetFileInfo(ctx, tempPath)
	if err != nil {
		return fmt.Errorf("inspect staged OpenSandbox file: %w", mapOpenSandboxError(err))
	}
	file, ok := info[tempPath]
	if !ok && len(info) == 1 {
		for _, candidate := range info {
			file = candidate
			ok = true
		}
	}
	if !ok || file.Type != "file" || file.Size != transfer.Size {
		return fmt.Errorf("staged OpenSandbox file metadata did not match the upload contract")
	}
	reader, err := sandbox.DownloadFile(ctx, tempPath, "")
	if err != nil {
		return fmt.Errorf("verify staged OpenSandbox file: %w", mapOpenSandboxError(err))
	}
	hasher := sha256.New()
	written, copyErr := io.Copy(hasher, reader)
	closeErr := reader.Close()
	if copyErr != nil || closeErr != nil {
		return errors.Join(copyErr, closeErr)
	}
	if written != transfer.Size || hex.EncodeToString(hasher.Sum(nil)) != transfer.SHA256 {
		return fmt.Errorf("staged OpenSandbox file content did not match the upload contract")
	}
	return nil
}

func (p *OpenSandboxProvider) cleanupOpenSandboxStaging(
	tempPath string,
	sandbox *opensandbox.Sandbox,
	operationErr error,
) error {
	cleanupCtx, cancel := context.WithTimeout(context.Background(), providerCleanupTimeout)
	defer cancel()
	cleanupErr := mapOpenSandboxError(sandbox.DeleteFiles(cleanupCtx, []string{tempPath}))
	if cleanupErr != nil {
		cleanupErr = fmt.Errorf("delete staged OpenSandbox file: %w", cleanupErr)
	}
	return errors.Join(operationErr, cleanupErr)
}

func (p *OpenSandboxProvider) OpenFile(ctx context.Context, session *Session, remotePath string) (*FileDownload, error) {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return nil, err
	}
	info, err := sandbox.GetFileInfo(ctx, remotePath)
	if err != nil {
		var apiErr *opensandbox.APIError
		if errors.As(err, &apiErr) && apiErr.StatusCode == http.StatusNotFound {
			return nil, fmt.Errorf("%w: %v", ErrFileNotFound, err)
		}
		return nil, mapOpenSandboxError(err)
	}
	file, ok := info[remotePath]
	if !ok && len(info) == 1 {
		for _, candidate := range info {
			file = candidate
			ok = true
		}
	}
	if !ok || file.Size < 0 {
		return nil, fmt.Errorf("OpenSandbox returned no valid metadata for %s", remotePath)
	}
	reader, err := sandbox.DownloadFile(ctx, remotePath, "")
	if err != nil {
		var apiErr *opensandbox.APIError
		if errors.As(err, &apiErr) && apiErr.StatusCode == http.StatusNotFound {
			return nil, fmt.Errorf("%w: %v", ErrFileNotFound, err)
		}
		return nil, mapOpenSandboxError(err)
	}
	mode, err := openSandboxModeFromAPI(file.Mode)
	if err != nil {
		reader.Close()
		return nil, fmt.Errorf("OpenSandbox returned invalid file mode for %s: %w", remotePath, err)
	}
	return &FileDownload{Content: reader, Size: file.Size, Mode: mode}, nil
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

func (p *OpenSandboxProvider) AuditWorkspace(ctx context.Context, session *Session) (WorkspaceUsage, error) {
	sandbox, err := p.connect(ctx, session)
	if err != nil {
		return WorkspaceUsage{}, err
	}
	return auditWorkspaceFilesystem(ctx, p.Name(), WorkspaceRoot, func(ctx context.Context, directory string) ([]workspaceEntry, error) {
		files, err := sandbox.ListDirectoryWithDepth(ctx, directory, 1)
		if err != nil {
			return nil, mapOpenSandboxError(err)
		}
		entries := make([]workspaceEntry, 0, len(files))
		for _, file := range files {
			kind := workspaceEntryKind(0)
			switch file.Type {
			case "file":
				kind = workspaceEntryFile
			case "directory", "dir":
				kind = workspaceEntryDirectory
			case "symlink", "link":
				kind = workspaceEntrySymlink
			}
			entries = append(entries, workspaceEntry{Path: file.Path, Kind: kind, Size: file.Size})
		}
		return entries, nil
	})
}

func (p *OpenSandboxProvider) Delete(ctx context.Context, session *Session) error {
	if session == nil || session.ID == "" {
		return fmt.Errorf("OpenSandbox session identity is required")
	}
	return mapOpenSandboxError(opensandbox.NewSandboxManager(p.cfg.Connection).KillSandbox(ctx, session.ID))
}

func (p *OpenSandboxProvider) List(ctx context.Context, workspaceID string) ([]SandboxStatus, error) {
	if workspaceID == "" {
		return nil, fmt.Errorf("workspace_id is required")
	}
	manager := opensandbox.NewSandboxManager(p.cfg.Connection)
	result := make([]SandboxStatus, 0)
	for page := 1; page <= maxOpenSandboxInventoryPages; page++ {
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
			if metadata["agentarea.workspace_id"] != workspaceID {
				return nil, fmt.Errorf("OpenSandbox inventory returned sandbox %s outside workspace scope", info.ID)
			}
			if metadata["agentarea.provisioning_id"] == "" {
				return nil, fmt.Errorf("OpenSandbox inventory sandbox %s has no provisioning identity", info.ID)
			}
			taskID := metadata["agentarea.task_id"]
			if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
				return nil, fmt.Errorf("OpenSandbox inventory sandbox %s has invalid task identity: %w", info.ID, err)
			}
			expectedMetadata := map[string]string{
				"agentarea.isolation":        p.cfg.Isolation,
				"agentarea.resource_cpu":     p.cfg.ResourceCPU,
				"agentarea.resource_memory":  p.cfg.ResourceMemory,
				"agentarea.resource_storage": p.cfg.ResourceStorage,
				"agentarea.egress_mode":      p.cfg.EgressMode,
			}
			for name, expected := range expectedMetadata {
				if metadata[name] != expected {
					return nil, fmt.Errorf("OpenSandbox inventory sandbox %s has untrusted %s metadata", info.ID, name)
				}
			}
			result = append(result, SandboxStatus{
				ID:          info.ID,
				Provider:    p.Name(),
				WorkspaceID: metadata["agentarea.workspace_id"],
				TaskID:      taskID,
				State:       strings.ToLower(string(info.Status.State)),
				CreatedAt:   info.CreatedAt,
				ExpiresAt:   info.ExpiresAt,
				Resources: map[string]string{
					"cpu":     metadata["agentarea.resource_cpu"],
					"memory":  metadata["agentarea.resource_memory"],
					"storage": metadata["agentarea.resource_storage"],
				},
				Isolation: metadata["agentarea.isolation"],
			})
		}
		if !response.Pagination.HasNextPage {
			sort.Slice(result, func(i, j int) bool {
				return result[i].CreatedAt.After(result[j].CreatedAt)
			})
			return result, nil
		}
	}
	return nil, fmt.Errorf("OpenSandbox inventory exceeded %d pages", maxOpenSandboxInventoryPages)
}

func (p *OpenSandboxProvider) connect(ctx context.Context, session *Session) (*opensandbox.Sandbox, error) {
	sandbox, err := opensandbox.ConnectSandbox(ctx, p.cfg.Connection, session.ID)
	if err != nil {
		return nil, mapOpenSandboxError(err)
	}
	return sandbox, nil
}

func (p *OpenSandboxProvider) artifacts(ctx context.Context, sandbox *opensandbox.Sandbox, paths []string) ([]sandboxcontract.SandboxArtifact, error) {
	artifacts := make([]sandboxcontract.SandboxArtifact, 0, len(paths))
	for _, requested := range paths {
		remotePath, err := sandboxPath(requested)
		if err != nil {
			return nil, err
		}
		info, err := sandbox.GetFileInfo(ctx, remotePath)
		if err != nil {
			artifacts = append(artifacts, sandboxcontract.SandboxArtifact{Path: requested, Error: mapOpenSandboxError(err).Error()})
			continue
		}
		file, ok := info[remotePath]
		if !ok && len(info) == 1 {
			for _, candidate := range info {
				file = candidate
				ok = true
			}
		}
		if !ok || file.Type != "file" || file.Size < 0 {
			artifacts = append(artifacts, sandboxcontract.SandboxArtifact{Path: requested, Error: "artifact metadata is invalid"})
			continue
		}
		artifacts = append(artifacts, sandboxcontract.SandboxArtifact{
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

func openSandboxNetworkPolicy(allowInternet bool) *opensandbox.NetworkPolicy {
	defaultAction := "deny"
	if allowInternet {
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

// OpenSandbox's execd API represents POSIX permissions as decimal integers
// whose digits are octal (for example 600 and 755), not as the integer value of
// Go's fs.FileMode (384 and 493 respectively). Keep that wire-format quirk at
// the adapter boundary so the provider-neutral runtime continues to use real
// permission bits.
func openSandboxModeToAPI(mode fs.FileMode) (int, error) {
	normalized, err := normalizeFileMode(mode)
	if err != nil {
		return 0, err
	}
	value, err := strconv.Atoi(strconv.FormatUint(uint64(normalized.Perm()), 8))
	if err != nil {
		return 0, fmt.Errorf("encode OpenSandbox file mode: %w", err)
	}
	return value, nil
}

func openSandboxModeFromAPI(mode int) (fs.FileMode, error) {
	if mode < 0 {
		return 0, fmt.Errorf("file mode must be non-negative")
	}
	value, err := strconv.ParseUint(strconv.Itoa(mode), 8, 32)
	if err != nil || value > 0o777 {
		return 0, fmt.Errorf("file mode %d is not a three-digit octal permission", mode)
	}
	return fs.FileMode(value), nil
}
