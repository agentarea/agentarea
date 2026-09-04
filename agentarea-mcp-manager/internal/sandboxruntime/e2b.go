package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"mime/multipart"
	"net/http"
	"net/url"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"connectrpc.com/connect"
	"github.com/agentarea/mcp-manager/internal/execsupervisor"

	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	process "github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto/processconnect"
)

const e2bEnvdPort = 49999

const maxIsolationAttestationBytes = 64 * 1024

const maxE2BInventoryPages = 10_000

type E2BConfig struct {
	ProviderName        string
	APIURL              string
	APIKey              string
	SandboxURL          string
	Template            string
	LeaseTTL            time.Duration
	RequestTimeout      time.Duration
	AllowInternetAccess bool
	AllowInsecure       bool
	// Isolation is the boundary the operator declared for this deployment. The
	// sandbox must attest to exactly this value before it runs task code.
	Isolation string
	// RuntimeIdentity optionally pins the attested runtime build.
	RuntimeIdentity string
	// AttestationPath is where the template publishes its attestation document.
	AttestationPath string
}

type E2BProvider struct {
	cfg             E2BConfig
	lifecycleClient *http.Client
	envdClient      *http.Client
}

type e2bCreateResponse struct {
	SandboxID          string `json:"sandboxID"`
	Domain             string `json:"domain"`
	EnvdVersion        string `json:"envdVersion"`
	EnvdAccessToken    string `json:"envdAccessToken"`
	TrafficAccessToken string `json:"trafficAccessToken"`
}

type e2bFilesystemEntry struct {
	Name string `json:"name"`
	Type string `json:"type"`
	Path string `json:"path"`
	Size int64  `json:"size"`
	Mode uint32 `json:"mode"`
}

type e2bStatResponse struct {
	Entry e2bFilesystemEntry `json:"entry"`
}

type e2bListDirResponse struct {
	Entries []e2bFilesystemEntry `json:"entries"`
}

// e2bListedSandbox decodes only inventory-safe fields. Access tokens returned
// alongside them are intentionally absent so they cannot be surfaced.
type e2bListedSandbox struct {
	SandboxID  string            `json:"sandboxID"`
	TemplateID string            `json:"templateID"`
	State      string            `json:"state"`
	StartedAt  time.Time         `json:"startedAt"`
	EndAt      *time.Time        `json:"endAt"`
	CPUCount   int               `json:"cpuCount"`
	MemoryMB   int               `json:"memoryMB"`
	Metadata   map[string]string `json:"metadata"`
}

func NewE2BProvider(cfg E2BConfig) (*E2BProvider, error) {
	if cfg.ProviderName != "e2b" && cfg.ProviderName != "cube" {
		return nil, fmt.Errorf("E2B-compatible provider name must be e2b or cube")
	}
	parsed, err := url.Parse(cfg.APIURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("%s API URL must be an absolute URL", cfg.ProviderName)
	}
	insecureAllowed := parsed.Scheme == "http" && cfg.AllowInsecure
	if parsed.Scheme != "https" && !insecureAllowed {
		return nil, fmt.Errorf("%s API URL must use HTTPS unless insecure development mode is explicitly enabled", cfg.ProviderName)
	}
	if cfg.APIKey == "" {
		return nil, fmt.Errorf("%s API key is required", cfg.ProviderName)
	}
	if cfg.LeaseTTL <= 0 {
		return nil, fmt.Errorf("%s task lease TTL must be positive", cfg.ProviderName)
	}
	// An E2B-compatible endpoint answering HTTP proves nothing about its
	// isolation boundary, so the deployment must declare one up front and the
	// sandbox must attest to it before any task code runs.
	if err := ValidateIsolationRequirement(IsolationRequirement{
		Provider:        cfg.ProviderName,
		Isolation:       cfg.Isolation,
		RuntimeIdentity: cfg.RuntimeIdentity,
	}); err != nil {
		return nil, err
	}
	if strings.TrimSpace(cfg.AttestationPath) == "" {
		return nil, fmt.Errorf("%s isolation attestation path is required", cfg.ProviderName)
	}
	if cfg.RequestTimeout <= 0 {
		cfg.RequestTimeout = 30 * time.Second
	}
	return &E2BProvider{
		cfg: cfg,
		lifecycleClient: &http.Client{
			Timeout: cfg.RequestTimeout,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return fmt.Errorf("unexpected redirect from E2B-compatible endpoint")
			},
		},
		envdClient: &http.Client{
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
				return fmt.Errorf("unexpected redirect from E2B-compatible sandbox")
			},
		},
	}, nil
}

func (p *E2BProvider) Name() string { return p.cfg.ProviderName }

func (p *E2BProvider) ProvisioningTimeout() time.Duration { return p.cfg.RequestTimeout }

func (p *E2BProvider) Create(ctx context.Context, req CreateRequest) (*Session, error) {
	if req.ProvisioningID == "" {
		return nil, fmt.Errorf("%s provisioning identity is required", p.Name())
	}
	template := p.cfg.Template
	if template == "" {
		return nil, fmt.Errorf("%s template is not configured", p.Name())
	}
	body := map[string]any{
		"templateID":            template,
		"timeout":               int(p.cfg.LeaseTTL.Seconds()),
		"secure":                true,
		"allow_internet_access": p.cfg.AllowInternetAccess,
		"metadata": map[string]string{
			"agentarea.provisioning_id": req.ProvisioningID,
			"agentarea.workspace_id":    req.WorkspaceID,
			"agentarea.task_id":         req.TaskID,
		},
	}
	var created e2bCreateResponse
	if err := p.lifecycleJSON(ctx, http.MethodPost, "/sandboxes", body, &created); err != nil {
		return nil, err
	}
	session := &Session{ID: created.SandboxID}
	if created.SandboxID == "" || created.EnvdVersion == "" {
		if created.SandboxID == "" {
			return nil, fmt.Errorf("%s returned an incomplete sandbox response", p.Name())
		}
		return session, fmt.Errorf("%s returned an incomplete sandbox response", p.Name())
	}
	envdURL, err := p.envdURL(created.SandboxID, created.Domain)
	if err != nil {
		return session, err
	}
	session.Data = map[string]string{
		"envd_url":             envdURL,
		"envd_version":         created.EnvdVersion,
		"envd_access_token":    created.EnvdAccessToken,
		"traffic_access_token": created.TrafficAccessToken,
		"isolation":            p.cfg.Isolation,
	}
	if err := p.makeDirectory(ctx, session, WorkspaceRoot); err != nil {
		return session, fmt.Errorf("initialize %s workspace: %w", p.Name(), err)
	}
	if attestErr := p.attestIsolation(ctx, session); attestErr != nil {
		return session, attestErr
	}
	if err := p.verifyExecutionSupervisor(ctx, session, req.Supervisor); err != nil {
		return session, err
	}
	if _, err := p.AuditWorkspace(ctx, session); err != nil {
		return session, fmt.Errorf("verify %s workspace accounting: %w", p.Name(), err)
	}
	return session, nil
}

func (p *E2BProvider) ResolveProvisioning(
	ctx context.Context,
	intent ProvisioningIntent,
) ([]*Session, error) {
	if err := intent.validate(p.Name()); err != nil {
		return nil, err
	}
	metadata := map[string]string{
		"agentarea.provisioning_id": intent.ProvisioningID,
		"agentarea.workspace_id":    intent.WorkspaceID,
		"agentarea.task_id":         intent.TaskID,
	}
	listed, err := p.listSandboxes(ctx, metadata)
	if err != nil {
		return nil, err
	}
	result := make([]*Session, 0, len(listed))
	for _, item := range listed {
		for name, expected := range metadata {
			if item.Metadata[name] != expected {
				return nil, fmt.Errorf("%s provisioning match %s has inconsistent %s", p.Name(), item.SandboxID, name)
			}
		}
		if item.SandboxID == "" {
			return nil, fmt.Errorf("%s provisioning inventory returned an empty sandbox identity", p.Name())
		}
		result = append(result, &Session{ID: item.SandboxID})
	}
	return result, nil
}

func (p *E2BProvider) Renew(ctx context.Context, session *Session, ttl time.Duration) error {
	return p.lifecycleJSON(ctx, http.MethodPost, "/sandboxes/"+url.PathEscape(session.ID)+"/timeout", map[string]int{
		"timeout": int(ttl.Seconds()),
	}, nil)
}

func (p *E2BProvider) ExecuteQuiescent(ctx context.Context, session *Session, executionRequest QuiescentExecution) (*sandboxcontract.ExecuteResponse, error) {
	timeout, err := executionRequest.validate()
	if err != nil {
		return nil, err
	}
	if err := p.verifyExecutionSupervisor(ctx, session, executionRequest.Supervisor); err != nil {
		return nil, err
	}
	req := executionRequest.Request
	statusPath, err := execsupervisor.StatusPath(uuid.NewString())
	if err != nil {
		return nil, err
	}
	args, err := execsupervisor.RunArgs(
		executionRequest.Supervisor,
		statusPath,
		timeout,
		executionRequest.MaxFileBytes,
		"/bin/sh", "-c", req.CommandBody,
	)
	if err != nil {
		return nil, err
	}
	started := time.Now()
	stdout, stderr, exitCode, stdoutTruncated, stderrTruncated, err := p.runProcess(
		ctx, session, executionRequest.Supervisor.Path, args, WorkspaceRoot,
		timeout+supervisorCleanupGraceSeconds,
		req.StdoutMaxBytes,
		req.StderrMaxBytes,
	)
	if err != nil {
		return nil, err
	}
	if exitCode != 0 {
		return nil, fmt.Errorf("%s execution supervisor exited with code %d", p.Name(), exitCode)
	}
	statusCtx, cancelStatus := context.WithTimeout(context.WithoutCancel(ctx), providerCleanupTimeout)
	status, statusErr := p.readExecutionStatus(statusCtx, session, statusPath, executionRequest.Supervisor)
	cleanupErr := p.removeFile(statusCtx, session, statusPath)
	cancelStatus()
	if errors.Is(cleanupErr, ErrFileNotFound) {
		cleanupErr = nil
	}
	if statusErr != nil || cleanupErr != nil {
		return nil, errors.Join(statusErr, cleanupErr)
	}
	result := &sandboxcontract.ExecuteResponse{
		Stdout:          stdout,
		Stderr:          stderr,
		StdoutTruncated: stdoutTruncated,
		StderrTruncated: stderrTruncated,
		ExitCode:        status.ChildExitCode,
		ExecutionTimeMs: time.Since(started).Milliseconds(),
	}
	result.Artifacts, err = p.artifacts(ctx, session, req.ArtifactPaths)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (p *E2BProvider) verifyExecutionSupervisor(
	ctx context.Context,
	session *Session,
	expected execsupervisor.Attestation,
) error {
	download, err := p.OpenFile(ctx, session, expected.Path)
	if err != nil {
		return fmt.Errorf("inspect %s execution supervisor: %w", p.Name(), err)
	}
	if download.Mode.Perm()&0o022 != 0 || download.Mode.Perm()&0o100 == 0 {
		_ = download.Content.Close()
		return fmt.Errorf("%s execution supervisor must be executable and not group/other writable", p.Name())
	}
	return verifySupervisorDownload(download, expected)
}

func (p *E2BProvider) readExecutionStatus(
	ctx context.Context,
	session *Session,
	statusPath string,
	expected execsupervisor.Attestation,
) (execsupervisor.Status, error) {
	download, err := p.OpenFile(ctx, session, statusPath)
	if err != nil {
		return execsupervisor.Status{}, fmt.Errorf("read %s execution status: %w", p.Name(), err)
	}
	if download.Mode.Perm() != 0o600 {
		_ = download.Content.Close()
		return execsupervisor.Status{}, fmt.Errorf("%s execution status must use mode 0600", p.Name())
	}
	return decodeSupervisorStatusDownload(download, expected)
}

func (p *E2BProvider) PutFile(ctx context.Context, session *Session, transfer FileUpload, content io.Reader) error {
	tempPath, err := stagingPath(transfer.Path)
	if err != nil {
		return err
	}
	if err := p.uploadFile(ctx, session, tempPath, content, transfer.Size); err != nil {
		return err
	}
	if err := p.verifyE2BUpload(ctx, session, tempPath, transfer); err != nil {
		return p.cleanupE2BStaging(session, tempPath, err)
	}
	if err := p.moveFile(ctx, session, tempPath, transfer.Path); err != nil {
		return p.cleanupE2BStaging(session, tempPath, fmt.Errorf("%s atomic file commit: %w", p.Name(), err))
	}
	return nil
}

func (p *E2BProvider) uploadFile(ctx context.Context, session *Session, remotePath string, content io.Reader, size int64) error {
	endpoint, err := p.fileURL(session, remotePath)
	if err != nil {
		return err
	}
	pipeReader, pipeWriter := io.Pipe()
	multipartWriter := multipart.NewWriter(pipeWriter)
	writeDone := make(chan error, 1)
	go func() {
		part, createErr := multipartWriter.CreateFormFile("file", path.Base(remotePath))
		if createErr == nil {
			_, createErr = io.Copy(part, content)
		}
		if closeErr := multipartWriter.Close(); createErr == nil {
			createErr = closeErr
		}
		_ = pipeWriter.CloseWithError(createErr)
		writeDone <- createErr
	}()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, pipeReader)
	if err != nil {
		pipeReader.Close()
		return err
	}
	req.Header.Set("Content-Type", multipartWriter.FormDataContentType())
	req.Header.Set("X-Agentarea-File-Size", strconv.FormatInt(size, 10))
	p.setEnvdHeaders(req.Header, session)
	resp, err := p.envdClient.Do(req)
	if err != nil {
		_ = pipeReader.CloseWithError(err)
		<-writeDone
		return fmt.Errorf("%s file upload: %w", p.Name(), err)
	}
	defer resp.Body.Close()
	// A server may reject the request before consuming its body. Closing the
	// reader unblocks the multipart goroutine instead of waiting forever.
	_ = pipeReader.Close()
	responseErr := mapE2BResponse(resp, "file upload")
	writeErr := <-writeDone
	if responseErr != nil {
		return responseErr
	}
	if writeErr != nil {
		return fmt.Errorf("%s file upload body: %w", p.Name(), writeErr)
	}
	return nil
}

func (p *E2BProvider) OpenFile(ctx context.Context, session *Session, remotePath string) (*FileDownload, error) {
	entry, statErr := p.statFile(ctx, session, remotePath)
	if statErr != nil {
		return nil, statErr
	}
	if entry.Type != "FILE_TYPE_FILE" && entry.Type != "file" {
		return nil, ErrFileNotFound
	}
	if entry.Size < 0 || entry.Mode&^uint32(0o777) != 0 {
		return nil, fmt.Errorf("%s file stat returned invalid size or mode", p.Name())
	}
	endpoint, err := p.fileURL(session, remotePath)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	p.setEnvdHeaders(req.Header, session)
	resp, err := p.envdClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s file download: %w", p.Name(), err)
	}
	if resp.StatusCode == http.StatusNotFound {
		resp.Body.Close()
		return nil, ErrFileNotFound
	}
	if err := mapE2BResponse(resp, "file download"); err != nil {
		resp.Body.Close()
		return nil, err
	}
	if resp.ContentLength >= 0 && resp.ContentLength != entry.Size {
		resp.Body.Close()
		return nil, fmt.Errorf("%s file download size changed before read", p.Name())
	}
	return &FileDownload{Content: resp.Body, Size: entry.Size, Mode: fs.FileMode(entry.Mode)}, nil
}

func (p *E2BProvider) ListFiles(ctx context.Context, session *Session, remotePrefix string) ([]string, error) {
	entry, err := p.statFile(ctx, session, remotePrefix)
	if errors.Is(err, ErrSessionNotFound) || errors.Is(err, ErrFileNotFound) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if entry.Type == "FILE_TYPE_FILE" || entry.Type == "file" {
		return []string{entry.Path}, nil
	}
	paths, err := p.listFileTree(ctx, session, remotePrefix)
	if err != nil {
		return nil, err
	}
	sort.Strings(paths)
	return paths, nil
}

func (p *E2BProvider) AuditWorkspace(ctx context.Context, session *Session) (WorkspaceUsage, error) {
	return auditWorkspaceFilesystem(ctx, p.Name(), WorkspaceRoot, func(ctx context.Context, directory string) ([]workspaceEntry, error) {
		entries, err := p.listDirectory(ctx, session, directory)
		if err != nil {
			return nil, err
		}
		result := make([]workspaceEntry, 0, len(entries))
		for _, entry := range entries {
			kind := workspaceEntryKind(0)
			switch entry.Type {
			case "FILE_TYPE_FILE", "file":
				kind = workspaceEntryFile
			case "FILE_TYPE_DIRECTORY", "directory", "dir":
				kind = workspaceEntryDirectory
			case "FILE_TYPE_SYMLINK", "symlink", "link":
				kind = workspaceEntrySymlink
			}
			result = append(result, workspaceEntry{Path: entry.Path, Kind: kind, Size: entry.Size})
		}
		return result, nil
	})
}

// attestIsolation reads the attestation the sandbox template publishes and
// holds it against the declared deployment posture. There is no weaker tier to
// fall back to: an unproven boundary means the profile is unavailable.
func (p *E2BProvider) attestIsolation(ctx context.Context, session *Session) error {
	download, err := p.OpenFile(ctx, session, p.cfg.AttestationPath)
	if err != nil {
		return fmt.Errorf("%w: read %s isolation attestation: %v", ErrIsolationUnavailable, p.Name(), err)
	}
	defer download.Content.Close()
	if download.Size <= 0 || download.Size > maxIsolationAttestationBytes {
		return fmt.Errorf(
			"%w: %s published no bounded isolation attestation at %s",
			ErrIsolationUnavailable, p.Name(), p.cfg.AttestationPath,
		)
	}
	content, err := io.ReadAll(io.LimitReader(download.Content, maxIsolationAttestationBytes+1))
	if err != nil || int64(len(content)) != download.Size {
		return fmt.Errorf("%w: read %s isolation attestation: %v", ErrIsolationUnavailable, p.Name(), err)
	}
	attestation, err := DecodeIsolationAttestation(string(content))
	if err != nil {
		return fmt.Errorf("%w: %s: %v", ErrIsolationUnavailable, p.Name(), err)
	}
	return attestation.Verify(IsolationRequirement{
		Provider:        p.Name(),
		Isolation:       p.cfg.Isolation,
		RuntimeIdentity: p.cfg.RuntimeIdentity,
	})
}

// List reports the live provider inventory for one workspace. Only the fields
// below are decoded, so envd and traffic access tokens present in the provider
// response never reach the control-plane API.
func (p *E2BProvider) List(ctx context.Context, workspaceID string) ([]SandboxStatus, error) {
	if workspaceID == "" {
		return nil, fmt.Errorf("workspace_id is required")
	}
	listed, err := p.listSandboxes(ctx, map[string]string{"agentarea.workspace_id": workspaceID})
	if err != nil {
		return nil, fmt.Errorf("%s inventory: %w", p.Name(), err)
	}
	result := make([]SandboxStatus, 0, len(listed))
	for _, item := range listed {
		if item.Metadata["agentarea.workspace_id"] != workspaceID || item.SandboxID == "" {
			return nil, fmt.Errorf("%s inventory returned a sandbox outside the requested workspace", p.Name())
		}
		if item.Metadata["agentarea.provisioning_id"] == "" {
			return nil, fmt.Errorf("%s inventory sandbox %s has no provisioning identity", p.Name(), item.SandboxID)
		}
		resources := map[string]string{}
		if item.CPUCount > 0 {
			resources["cpu"] = strconv.Itoa(item.CPUCount)
		}
		if item.MemoryMB > 0 {
			resources["memory"] = strconv.Itoa(item.MemoryMB) + "Mi"
		}
		if item.TemplateID != "" {
			resources["template"] = item.TemplateID
		}
		result = append(result, SandboxStatus{
			ID:          item.SandboxID,
			Provider:    p.Name(),
			WorkspaceID: workspaceID,
			TaskID:      item.Metadata["agentarea.task_id"],
			State:       item.State,
			CreatedAt:   item.StartedAt,
			ExpiresAt:   item.EndAt,
			Resources:   resources,
			Isolation:   p.cfg.Isolation,
		})
	}
	sort.Slice(result, func(i, j int) bool { return result[i].ID < result[j].ID })
	return result, nil
}

// listSandboxes uses the current paginated E2B inventory API. Metadata filters
// are applied by the provider and verified again by each caller; a repeated or
// unbounded pagination token fails loudly instead of returning a partial view.
func (p *E2BProvider) listSandboxes(
	ctx context.Context,
	metadata map[string]string,
) ([]e2bListedSandbox, error) {
	innerMetadata := url.Values{}
	for name, value := range metadata {
		innerMetadata.Set(name, value)
	}
	result := make([]e2bListedSandbox, 0)
	nextToken := ""
	seenTokens := make(map[string]struct{})
	for page := 0; page < maxE2BInventoryPages; page++ {
		endpoint, err := url.Parse(strings.TrimRight(p.cfg.APIURL, "/") + "/v2/sandboxes")
		if err != nil {
			return nil, err
		}
		query := endpoint.Query()
		query.Set("limit", "100")
		if encoded := innerMetadata.Encode(); encoded != "" {
			query.Set("metadata", encoded)
		}
		if nextToken != "" {
			query.Set("nextToken", nextToken)
		}
		endpoint.RawQuery = query.Encode()
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint.String(), nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("X-API-KEY", p.cfg.APIKey)
		req.Header.Set("Accept", "application/json")
		resp, err := p.lifecycleClient.Do(req)
		if err != nil {
			return nil, fmt.Errorf("%s inventory request: %w", p.Name(), err)
		}
		if responseErr := mapE2BResponse(resp, "inventory request"); responseErr != nil {
			resp.Body.Close()
			return nil, responseErr
		}
		var pageItems []e2bListedSandbox
		decodeErr := json.NewDecoder(io.LimitReader(resp.Body, 2*1024*1024)).Decode(&pageItems)
		closeErr := resp.Body.Close()
		if decodeErr != nil || closeErr != nil {
			return nil, errors.Join(decodeErr, closeErr)
		}
		result = append(result, pageItems...)
		nextToken = strings.TrimSpace(resp.Header.Get("X-Next-Token"))
		if nextToken == "" {
			return result, nil
		}
		if _, duplicate := seenTokens[nextToken]; duplicate {
			return nil, fmt.Errorf("%s inventory repeated pagination token", p.Name())
		}
		seenTokens[nextToken] = struct{}{}
	}
	return nil, fmt.Errorf("%s inventory exceeded %d pages", p.Name(), maxE2BInventoryPages)
}

func (p *E2BProvider) Delete(ctx context.Context, session *Session) error {
	return p.lifecycleJSON(ctx, http.MethodDelete, "/sandboxes/"+url.PathEscape(session.ID), nil, nil)
}

func (p *E2BProvider) runProcess(
	ctx context.Context,
	session *Session,
	command string,
	args []string,
	cwd string,
	timeoutSeconds int,
	stdoutMaxBytes int64,
	stderrMaxBytes int64,
) (string, string, int, bool, bool, error) {
	envdURL := session.Data["envd_url"]
	if envdURL == "" {
		return "", "", 0, false, false, fmt.Errorf("%s session has no envd URL", p.Name())
	}
	stdoutLimit, err := outputCaptureLimit(stdoutMaxBytes)
	if err != nil {
		return "", "", 0, false, false, err
	}
	stderrLimit, err := outputCaptureLimit(stderrMaxBytes)
	if err != nil {
		return "", "", 0, false, false, err
	}
	client := processconnect.NewProcessClient(p.envdClient, envdURL)
	stdin := false
	request := connect.NewRequest(&process.StartRequest{
		Process: &process.ProcessConfig{
			Cmd:  command,
			Args: args,
			Cwd:  &cwd,
		},
		Stdin: &stdin,
	})
	p.setEnvdHeaders(request.Header(), session)
	if timeoutSeconds <= 0 {
		return "", "", 0, false, false, fmt.Errorf("E2B process timeout must be positive")
	}
	ctx, cancel := context.WithTimeout(
		ctx,
		time.Duration(timeoutSeconds)*time.Second+execsupervisor.NetworkGrace,
	)
	defer cancel()
	request.Header().Set("Connect-Timeout-Ms", strconv.Itoa(timeoutSeconds*1000))

	stream, err := client.Start(ctx, request)
	if err != nil {
		return "", "", 0, false, false, mapE2BError(err)
	}
	defer stream.Close()

	stdout := newBoundedOutput(stdoutLimit)
	stderr := newBoundedOutput(stderrLimit)
	exitCode := 0
	ended := false
	for stream.Receive() {
		event := stream.Msg().GetEvent()
		if data := event.GetData(); data != nil {
			stdout.Write(data.GetStdout())
			stderr.Write(data.GetStderr())
		}
		if end := event.GetEnd(); end != nil {
			exitCode = int(end.GetExitCode())
			if end.GetError() != "" && stderr.String() == "" {
				stderr.Write([]byte(end.GetError()))
			}
			ended = true
		}
	}
	if err := stream.Err(); err != nil {
		return stdout.String(), stderr.String(), exitCode, stdout.Truncated(), stderr.Truncated(), mapE2BError(err)
	}
	if !ended {
		return stdout.String(), stderr.String(), exitCode, stdout.Truncated(), stderr.Truncated(), fmt.Errorf("%s command stream ended without an exit event", p.Name())
	}
	return stdout.String(), stderr.String(), exitCode, stdout.Truncated(), stderr.Truncated(), nil
}

func (p *E2BProvider) verifyE2BUpload(
	ctx context.Context,
	session *Session,
	tempPath string,
	transfer FileUpload,
) error {
	entry, err := p.statFile(ctx, session, tempPath)
	if err != nil {
		return fmt.Errorf("inspect staged %s file: %w", p.Name(), err)
	}
	if (entry.Type != "FILE_TYPE_FILE" && entry.Type != "file") || entry.Size != transfer.Size {
		return fmt.Errorf("staged %s file metadata did not match the upload contract", p.Name())
	}
	download, err := p.OpenFile(ctx, session, tempPath)
	if err != nil {
		return fmt.Errorf("verify staged %s file: %w", p.Name(), err)
	}
	hasher := sha256.New()
	written, copyErr := io.Copy(hasher, download.Content)
	closeErr := download.Content.Close()
	if copyErr != nil || closeErr != nil {
		return errors.Join(copyErr, closeErr)
	}
	if written != transfer.Size || hex.EncodeToString(hasher.Sum(nil)) != transfer.SHA256 {
		return fmt.Errorf("staged %s file content did not match the upload contract", p.Name())
	}
	normalizedMode, err := normalizeFileMode(transfer.Mode)
	if err != nil {
		return err
	}
	_, stderr, exitCode, _, _, err := p.runProcess(
		ctx,
		session,
		"/bin/chmod",
		[]string{fmt.Sprintf("%03o", normalizedMode.Perm()), tempPath},
		"/",
		30,
		0,
		4096,
	)
	if err != nil {
		return fmt.Errorf("set staged %s file mode: %w", p.Name(), err)
	}
	if exitCode != 0 {
		return fmt.Errorf("set staged %s file mode: %s", p.Name(), strings.TrimSpace(stderr))
	}
	entry, err = p.statFile(ctx, session, tempPath)
	if err != nil {
		return fmt.Errorf("verify staged %s file mode: %w", p.Name(), err)
	}
	if fs.FileMode(entry.Mode).Perm() != normalizedMode.Perm() {
		return fmt.Errorf("staged %s file mode did not match the upload contract", p.Name())
	}
	return nil
}

func (p *E2BProvider) cleanupE2BStaging(session *Session, tempPath string, operationErr error) error {
	cleanupCtx, cancel := context.WithTimeout(context.Background(), providerCleanupTimeout)
	defer cancel()
	cleanupErr := p.removeFile(cleanupCtx, session, tempPath)
	if cleanupErr != nil && !errors.Is(cleanupErr, ErrFileNotFound) {
		cleanupErr = fmt.Errorf("delete staged %s file: %w", p.Name(), cleanupErr)
	} else {
		cleanupErr = nil
	}
	return errors.Join(operationErr, cleanupErr)
}

func (p *E2BProvider) makeDirectory(ctx context.Context, session *Session, directory string) error {
	return p.filesystemJSON(ctx, session, "MakeDir", map[string]string{"path": directory}, nil)
}

func (p *E2BProvider) moveFile(ctx context.Context, session *Session, source, destination string) error {
	return p.filesystemJSON(ctx, session, "Move", map[string]string{
		"source": source, "destination": destination,
	}, nil)
}

func (p *E2BProvider) removeFile(ctx context.Context, session *Session, remotePath string) error {
	return p.filesystemJSON(ctx, session, "Remove", map[string]string{"path": remotePath}, nil)
}

func (p *E2BProvider) statFile(ctx context.Context, session *Session, remotePath string) (e2bFilesystemEntry, error) {
	var response e2bStatResponse
	if err := p.filesystemJSON(ctx, session, "Stat", map[string]string{"path": remotePath}, &response); err != nil {
		return e2bFilesystemEntry{}, err
	}
	if response.Entry.Path == "" {
		return e2bFilesystemEntry{}, fmt.Errorf("%s filesystem stat returned no entry", p.Name())
	}
	return response.Entry, nil
}

func (p *E2BProvider) listDirectory(ctx context.Context, session *Session, directory string) ([]e2bFilesystemEntry, error) {
	var response e2bListDirResponse
	if err := p.filesystemJSON(ctx, session, "ListDir", map[string]any{
		"path": directory, "depth": 1,
	}, &response); err != nil {
		return nil, err
	}
	return response.Entries, nil
}

func (p *E2BProvider) listFileTree(ctx context.Context, session *Session, root string) ([]string, error) {
	root = path.Clean(root)
	directories := []string{root}
	seen := map[string]struct{}{root: {}}
	files := make([]string, 0)
	entriesSeen := 0
	for len(directories) > 0 {
		directory := directories[0]
		directories = directories[1:]
		entries, err := p.listDirectory(ctx, session, directory)
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			entriesSeen++
			if entriesSeen > maxWorkspaceAuditEntries {
				return nil, fmt.Errorf("%s file listing exceeded %d entries", p.Name(), maxWorkspaceAuditEntries)
			}
			clean := path.Clean(entry.Path)
			if path.Dir(clean) != directory || !pathWithinRoot(root, clean) {
				return nil, fmt.Errorf("%s returned out-of-scope file entry %q", p.Name(), entry.Path)
			}
			if _, exists := seen[clean]; exists {
				return nil, fmt.Errorf("%s returned duplicate file entry %q", p.Name(), clean)
			}
			seen[clean] = struct{}{}
			switch entry.Type {
			case "FILE_TYPE_FILE", "file":
				files = append(files, clean)
			case "FILE_TYPE_DIRECTORY", "directory", "dir":
				directories = append(directories, clean)
			case "FILE_TYPE_SYMLINK", "symlink", "link":
				// The file API returns symlinks as metadata, not file content.
			default:
				return nil, fmt.Errorf("%s returned an unknown type for file entry %q", p.Name(), clean)
			}
		}
	}
	return files, nil
}

func (p *E2BProvider) filesystemJSON(
	ctx context.Context,
	session *Session,
	method string,
	body any,
	result any,
) error {
	envdURL := session.Data["envd_url"]
	if envdURL == "" {
		return fmt.Errorf("%s session has no envd URL", p.Name())
	}
	encoded, err := json.Marshal(body)
	if err != nil {
		return err
	}
	endpoint := strings.TrimRight(envdURL, "/") + "/filesystem.Filesystem/" + method
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(encoded))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Connect-Protocol-Version", "1")
	req.Header.Set("Connect-Timeout-Ms", strconv.FormatInt(p.cfg.RequestTimeout.Milliseconds(), 10))
	p.setEnvdHeaders(req.Header, session)
	resp, err := p.envdClient.Do(req)
	if err != nil {
		return fmt.Errorf("%s filesystem %s: %w", p.Name(), method, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return ErrFileNotFound
	}
	if err := mapE2BResponse(resp, "filesystem "+method); err != nil {
		return err
	}
	if result == nil || resp.StatusCode == http.StatusNoContent {
		return nil
	}
	decoder := json.NewDecoder(io.LimitReader(resp.Body, 64*1024*1024))
	if err := decoder.Decode(result); err != nil {
		return fmt.Errorf("%s filesystem %s response: %w", p.Name(), method, err)
	}
	return nil
}

func (p *E2BProvider) artifacts(ctx context.Context, session *Session, requested []string) ([]sandboxcontract.SandboxArtifact, error) {
	result := make([]sandboxcontract.SandboxArtifact, 0, len(requested))
	for _, relative := range requested {
		remotePath, err := sandboxPath(relative)
		if err != nil {
			return nil, err
		}
		entry, err := p.statFile(ctx, session, remotePath)
		if err != nil {
			if errors.Is(err, ErrFileNotFound) {
				result = append(result, sandboxcontract.SandboxArtifact{Path: relative, Error: "artifact file not found"})
				continue
			}
			result = append(result, sandboxcontract.SandboxArtifact{Path: relative, Error: "artifact inspection failed"})
			continue
		}
		if entry.Type != "FILE_TYPE_FILE" && entry.Type != "file" {
			result = append(result, sandboxcontract.SandboxArtifact{Path: relative, Error: "artifact path is not a regular file"})
			continue
		}
		if entry.Size < 0 {
			result = append(result, sandboxcontract.SandboxArtifact{Path: relative, Error: "artifact size is invalid"})
			continue
		}
		result = append(result, sandboxcontract.SandboxArtifact{Path: relative, Name: path.Base(relative), Size: entry.Size})
	}
	return result, nil
}

func (p *E2BProvider) lifecycleJSON(ctx context.Context, method, requestPath string, body any, result any) error {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(p.cfg.APIURL, "/")+requestPath, reader)
	if err != nil {
		return err
	}
	req.Header.Set("X-API-KEY", p.cfg.APIKey)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := p.lifecycleClient.Do(req)
	if err != nil {
		return fmt.Errorf("%s lifecycle request: %w", p.Name(), err)
	}
	defer resp.Body.Close()
	if err := mapE2BResponse(resp, "lifecycle request"); err != nil {
		return err
	}
	if result == nil || resp.StatusCode == http.StatusNoContent {
		return nil
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 2*1024*1024)).Decode(result); err != nil {
		return fmt.Errorf("%s lifecycle response: %w", p.Name(), err)
	}
	return nil
}

func (p *E2BProvider) fileURL(session *Session, remotePath string) (string, error) {
	envdURL := session.Data["envd_url"]
	if envdURL == "" {
		return "", fmt.Errorf("%s session has no envd URL", p.Name())
	}
	endpoint, err := url.Parse(strings.TrimRight(envdURL, "/") + "/files")
	if err != nil {
		return "", err
	}
	query := endpoint.Query()
	query.Set("path", remotePath)
	endpoint.RawQuery = query.Encode()
	return endpoint.String(), nil
}

func (p *E2BProvider) setEnvdHeaders(headers http.Header, session *Session) {
	headers.Set("E2b-Sandbox-Id", session.ID)
	headers.Set("E2b-Sandbox-Port", strconv.Itoa(e2bEnvdPort))
	if token := session.Data["envd_access_token"]; token != "" {
		headers.Set("X-Access-Token", token)
	}
	if token := session.Data["traffic_access_token"]; token != "" {
		headers.Set("E2b-Traffic-Access-Token", token)
	}
}

func (p *E2BProvider) envdURL(sandboxID, domain string) (string, error) {
	if p.cfg.SandboxURL != "" {
		parsed, err := url.Parse(p.cfg.SandboxURL)
		if err != nil || parsed.Scheme == "" || parsed.Host == "" {
			return "", fmt.Errorf("%s sandbox URL must be absolute", p.Name())
		}
		insecureAllowed := parsed.Scheme == "http" && p.cfg.AllowInsecure
		if parsed.Scheme != "https" && !insecureAllowed {
			return "", fmt.Errorf("%s sandbox URL must use HTTPS unless insecure development mode is explicitly enabled", p.Name())
		}
		return strings.TrimRight(parsed.String(), "/"), nil
	}
	if domain == "" {
		return "", fmt.Errorf("%s did not return a sandbox domain; configure SANDBOX_E2B_SANDBOX_URL", p.Name())
	}
	apiURL, _ := url.Parse(p.cfg.APIURL)
	scheme := "https"
	if apiURL.Scheme == "http" {
		scheme = "http"
	}
	return fmt.Sprintf("%s://%d-%s.%s", scheme, e2bEnvdPort, sandboxID, strings.TrimPrefix(domain, ".")), nil
}

func mapE2BResponse(resp *http.Response, operation string) error {
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return nil
	}
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	message := strings.TrimSpace(string(body))
	if resp.StatusCode == http.StatusNotFound {
		return fmt.Errorf("%w: %s returned 404: %s", ErrSessionNotFound, operation, message)
	}
	return fmt.Errorf("%s returned %d: %s", operation, resp.StatusCode, message)
}

func mapE2BError(err error) error {
	if err == nil {
		return nil
	}
	var connectErr *connect.Error
	if errors.As(err, &connectErr) && connectErr.Code() == connect.CodeNotFound {
		return fmt.Errorf("%w: %v", ErrSessionNotFound, err)
	}
	return err
}
