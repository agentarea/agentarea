package sandboxruntime

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"

	"connectrpc.com/connect"

	process "github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto"
	"github.com/agentarea/mcp-manager/internal/sandboxruntime/e2bproto/processconnect"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

const e2bEnvdPort = 49999

type E2BConfig struct {
	ProviderName   string
	APIURL         string
	APIKey         string
	SandboxURL     string
	Templates      map[string]string
	LeaseTTL       time.Duration
	RequestTimeout time.Duration
	InternetAccess map[string]bool
	AllowInsecure  bool
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

func NewE2BProvider(cfg E2BConfig) (*E2BProvider, error) {
	if cfg.ProviderName != "e2b" && cfg.ProviderName != "cube" {
		return nil, fmt.Errorf("E2B-compatible provider name must be e2b or cube")
	}
	parsed, err := url.Parse(cfg.APIURL)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("%s API URL must be an absolute URL", cfg.ProviderName)
	}
	if parsed.Scheme != "https" && !(parsed.Scheme == "http" && cfg.AllowInsecure) {
		return nil, fmt.Errorf("%s API URL must use HTTPS unless insecure development mode is explicitly enabled", cfg.ProviderName)
	}
	if cfg.APIKey == "" {
		return nil, fmt.Errorf("%s API key is required", cfg.ProviderName)
	}
	if cfg.LeaseTTL <= 0 {
		return nil, fmt.Errorf("%s task lease TTL must be positive", cfg.ProviderName)
	}
	if cfg.InternetAccess["locked"] {
		return nil, fmt.Errorf("%s package_install=locked cannot allow public internet access", cfg.ProviderName)
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

func (p *E2BProvider) Create(ctx context.Context, req CreateRequest) (*Session, error) {
	template := p.cfg.Templates[req.PackageInstall]
	if template == "" {
		return nil, fmt.Errorf("%s template for package_install=%s is not configured", p.Name(), req.PackageInstall)
	}
	body := map[string]any{
		"templateID":            template,
		"timeout":               int(p.cfg.LeaseTTL.Seconds()),
		"secure":                true,
		"allow_internet_access": p.cfg.InternetAccess[req.PackageInstall],
		"metadata": map[string]string{
			"agentarea.workspace_id":    req.WorkspaceID,
			"agentarea.task_id":         req.TaskID,
			"agentarea.package_install": req.PackageInstall,
		},
	}
	var created e2bCreateResponse
	if err := p.lifecycleJSON(ctx, http.MethodPost, "/sandboxes", body, &created); err != nil {
		return nil, err
	}
	if created.SandboxID == "" || created.EnvdVersion == "" {
		if created.SandboxID != "" {
			_ = p.lifecycleJSON(context.Background(), http.MethodDelete, "/sandboxes/"+url.PathEscape(created.SandboxID), nil, nil)
		}
		return nil, fmt.Errorf("%s returned an incomplete sandbox response", p.Name())
	}
	envdURL, err := p.envdURL(created.SandboxID, created.Domain)
	if err != nil {
		_ = p.lifecycleJSON(context.Background(), http.MethodDelete, "/sandboxes/"+url.PathEscape(created.SandboxID), nil, nil)
		return nil, err
	}
	session := &Session{
		ID: created.SandboxID,
		Data: map[string]string{
			"envd_url":             envdURL,
			"envd_version":         created.EnvdVersion,
			"envd_access_token":    created.EnvdAccessToken,
			"traffic_access_token": created.TrafficAccessToken,
		},
	}
	_, stderr, exitCode, _, _, err := p.runCommand(ctx, session, "true", 30, 0, 0)
	if err != nil || exitCode != 0 {
		_ = p.lifecycleJSON(context.Background(), http.MethodDelete, "/sandboxes/"+url.PathEscape(created.SandboxID), nil, nil)
		if err != nil {
			return nil, fmt.Errorf("initialize %s workspace: %w", p.Name(), err)
		}
		return nil, fmt.Errorf("initialize %s workspace: %s", p.Name(), strings.TrimSpace(stderr))
	}
	return session, nil
}

func (p *E2BProvider) Renew(ctx context.Context, session *Session, ttl time.Duration) error {
	return p.lifecycleJSON(ctx, http.MethodPost, "/sandboxes/"+url.PathEscape(session.ID)+"/timeout", map[string]int{
		"timeout": int(ttl.Seconds()),
	}, nil)
}

func (p *E2BProvider) Execute(ctx context.Context, session *Session, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	started := time.Now()
	command := "mkdir -p " + shellQuote(WorkspaceRoot) + " && cd " + shellQuote(WorkspaceRoot) + " && " + req.CommandBody
	stdout, stderr, exitCode, stdoutTruncated, stderrTruncated, err := p.runCommand(
		ctx,
		session,
		command,
		req.TimeoutSeconds,
		req.StdoutMaxBytes,
		req.StderrMaxBytes,
	)
	if err != nil {
		return nil, err
	}
	result := &warmpool.ExecuteResponse{
		Stdout:          stdout,
		Stderr:          stderr,
		StdoutTruncated: stdoutTruncated,
		StderrTruncated: stderrTruncated,
		ExitCode:        exitCode,
		ExecutionTimeMs: time.Since(started).Milliseconds(),
	}
	result.Artifacts, err = p.artifacts(ctx, session, req.ArtifactPaths)
	if err != nil {
		return nil, err
	}
	return result, nil
}

func (p *E2BProvider) PutFile(ctx context.Context, session *Session, remotePath string, content []byte) error {
	endpoint, err := p.fileURL(session, remotePath)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(content))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/octet-stream")
	p.setEnvdHeaders(req.Header, session)
	resp, err := p.envdClient.Do(req)
	if err != nil {
		return fmt.Errorf("%s file upload: %w", p.Name(), err)
	}
	defer resp.Body.Close()
	return mapE2BResponse(resp, "file upload")
}

func (p *E2BProvider) GetFile(ctx context.Context, session *Session, remotePath string) ([]byte, error) {
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
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, ErrFileNotFound
	}
	if err := mapE2BResponse(resp, "file download"); err != nil {
		return nil, err
	}
	content, err := io.ReadAll(io.LimitReader(resp.Body, 16*1024*1024+1))
	if err != nil {
		return nil, fmt.Errorf("%s file download body: %w", p.Name(), err)
	}
	if len(content) > 16*1024*1024 {
		return nil, fmt.Errorf("sandbox file exceeds 16 MiB response limit")
	}
	return content, nil
}

func (p *E2BProvider) ListFiles(ctx context.Context, session *Session, remotePrefix string) ([]string, error) {
	command := "if [ -d " + shellQuote(remotePrefix) + " ]; then find " + shellQuote(remotePrefix) + " -type f -print; elif [ -f " + shellQuote(remotePrefix) + " ]; then printf '%s\\n' " + shellQuote(remotePrefix) + "; fi"
	stdout, stderr, exitCode, _, _, err := p.runCommand(ctx, session, command, 30, 0, 0)
	if err != nil {
		return nil, err
	}
	if exitCode != 0 {
		return nil, fmt.Errorf("%s file listing failed: %s", p.Name(), strings.TrimSpace(stderr))
	}
	var paths []string
	for _, item := range strings.Split(stdout, "\n") {
		if item = strings.TrimSpace(item); item != "" {
			paths = append(paths, item)
		}
	}
	sort.Strings(paths)
	return paths, nil
}

func (p *E2BProvider) Delete(ctx context.Context, session *Session) error {
	return p.lifecycleJSON(ctx, http.MethodDelete, "/sandboxes/"+url.PathEscape(session.ID), nil, nil)
}

func (p *E2BProvider) runCommand(
	ctx context.Context,
	session *Session,
	command string,
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
	cwd := "/"
	request := connect.NewRequest(&process.StartRequest{
		Process: &process.ProcessConfig{
			Cmd:  "/bin/bash",
			Args: []string{"-l", "-c", command},
			Cwd:  &cwd,
		},
		Stdin: &stdin,
	})
	p.setEnvdHeaders(request.Header(), session)
	if timeoutSeconds <= 0 {
		timeoutSeconds = 120
	}
	ctx, cancel := context.WithTimeout(ctx, time.Duration(timeoutSeconds+5)*time.Second)
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

func (p *E2BProvider) artifacts(ctx context.Context, session *Session, requested []string) ([]warmpool.SandboxArtifact, error) {
	result := make([]warmpool.SandboxArtifact, 0, len(requested))
	for _, relative := range requested {
		remotePath, err := sandboxPath(relative)
		if err != nil {
			return nil, err
		}
		command := "if [ -f " + shellQuote(remotePath) + " ]; then stat -c '%s' -- " + shellQuote(remotePath) + "; else exit 44; fi"
		stdout, stderr, exitCode, _, _, err := p.runCommand(ctx, session, command, 30, 0, 0)
		if err != nil {
			return nil, err
		}
		if exitCode != 0 {
			result = append(result, warmpool.SandboxArtifact{Path: relative, Error: strings.TrimSpace(stderr)})
			continue
		}
		size, err := strconv.ParseInt(strings.TrimSpace(stdout), 10, 64)
		if err != nil {
			return nil, fmt.Errorf("%s returned an invalid artifact size for %s", p.Name(), relative)
		}
		result = append(result, warmpool.SandboxArtifact{Path: relative, Name: path.Base(relative), Size: size})
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
		if parsed.Scheme != "https" && !(parsed.Scheme == "http" && p.cfg.AllowInsecure) {
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

func shellQuote(value string) string {
	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}
