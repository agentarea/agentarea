package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"path"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/domain"
)

// Runtime is api.Runtime over the sandbox manager.
func (s *Service) Runtime() api.Runtime { return runtime{s} }

type runtime struct{ s *Service }

// fileTimeout is SandboxFileStore's timeout_seconds.
const fileTimeout = 300 * time.Second

func (r runtime) fileStore(workspaceID, taskID string) error {
	switch {
	case strings.TrimRight(r.s.d.Manager.URL, "/") == "":
		return errors.New("mcp_manager_url is required for the sandbox file store")
	case workspaceID == "":
		return errors.New("workspace_id is required for the sandbox file store")
	case taskID == "":
		return errors.New("task_id is required for the sandbox file store")
	case r.s.d.Manager.FileSecret == "":
		return errors.New("auth_secret is required for the sandbox file store")
	}
	return nil
}

func (r runtime) PutFile(ctx context.Context, workspaceID, taskID, p string, data []byte) (api.StoredFile, error) {
	if err := r.fileStore(workspaceID, taskID); err != nil {
		return api.StoredFile{}, err
	}
	sum := sha256.Sum256(data)
	q := url.Values{
		"workspace_id": {workspaceID}, "task_id": {taskID}, "path": {p},
		"size": {itoa(int64(len(data)))}, "sha256": {hex.EncodeToString(sum[:])}, "mode": {"600"},
	}
	h := bearer(r.s.d.Manager.FileSecret)
	h.Set("Content-Type", "application/octet-stream")
	resp, err := r.s.call(ctx, http.MethodPut, r.s.managerURL("/sandbox/file-content", q), h, data, fileTimeout)
	if err != nil {
		return api.StoredFile{}, err
	}
	if resp.Status >= 400 {
		return api.StoredFile{}, fmt.Errorf("sandbox file put failed for %s: HTTP %d: %s", domain.PyRepr(p), resp.Status, resp.text())
	}
	body, err := decodeObject(resp.Body)
	if err != nil {
		return api.StoredFile{}, err
	}
	out := api.StoredFile{Path: p, Size: int64(len(data))}
	if v, ok := body["path"]; ok {
		out.Path = strOf(v)
	}
	if v, ok := body["size"]; ok {
		out.Size = intOf(v)
	}
	return out, nil
}

func (r runtime) ReadFile(ctx context.Context, workspaceID, taskID, p string) ([]byte, string, error) {
	if err := r.fileStore(workspaceID, taskID); err != nil {
		return nil, "", err
	}
	q := url.Values{"workspace_id": {workspaceID}, "task_id": {taskID}, "path": {p}}
	resp, err := r.s.call(ctx, http.MethodGet, r.s.managerURL("/sandbox/file-content", q), bearer(r.s.d.Manager.FileSecret), nil, fileTimeout)
	if err != nil {
		return nil, "", err
	}
	if resp.Status == http.StatusNotFound {
		return nil, "", fmt.Errorf("%w: %s", api.ErrFileNotFound, p)
	}
	if resp.Status >= 400 {
		return nil, "", fmt.Errorf("sandbox file get failed for %s: HTTP %d: %s", domain.PyRepr(p), resp.Status, resp.text())
	}
	return resp.Body, resp.Header.Get("Content-Type"), nil
}

func (r runtime) ListFiles(ctx context.Context, workspaceID, taskID, prefix string) ([]string, error) {
	if err := r.fileStore(workspaceID, taskID); err != nil {
		return nil, err
	}
	q := url.Values{"workspace_id": {workspaceID}, "task_id": {taskID}, "list": {prefix}}
	resp, err := r.s.call(ctx, http.MethodGet, r.s.managerURL("/sandbox/files", q), bearer(r.s.d.Manager.FileSecret), nil, fileTimeout)
	if err != nil {
		return nil, err
	}
	if resp.Status >= 400 {
		return nil, fmt.Errorf("sandbox file list failed: HTTP %d: %s", resp.Status, resp.text())
	}
	body, err := decodeObject(resp.Body)
	if err != nil {
		return nil, err
	}
	raw, _ := body["paths"].([]any)
	out := make([]string, 0, len(raw))
	for _, p := range raw {
		out = append(out, strOf(p))
	}
	return out, nil
}

func (r runtime) FileExists(ctx context.Context, workspaceID, taskID, p string) (bool, error) {
	paths, err := r.ListFiles(ctx, workspaceID, taskID, p)
	if err != nil {
		return false, err
	}
	return containsString(paths, p), nil
}

// Manifest is fetch_runtime_manifest: GET /runtime/manifest, unauthenticated.
func (r runtime) Manifest(ctx context.Context) (*api.RuntimeManifest, error) {
	u := r.s.managerURL("/runtime/manifest", nil)
	fail := func(err error) error {
		r.s.d.Log.WarnContext(ctx, "runtime manifest fetch failed", "url", u, "error", err)
		return fmt.Errorf("%w: %w", api.ErrRuntimeUnavailable, err)
	}
	resp, err := r.s.call(ctx, http.MethodGet, u, nil, nil, 10*time.Second)
	if err != nil {
		return nil, fail(err)
	}
	if resp.Status >= 400 {
		return nil, fail(fmt.Errorf("HTTP %d", resp.Status))
	}
	m, err := validateManifest(resp.Body)
	if err != nil {
		return nil, fail(err)
	}
	return m, nil
}

// validateManifest is RuntimeManifest.model_validate.
func validateManifest(raw []byte) (*api.RuntimeManifest, error) {
	var m api.RuntimeManifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, err
	}
	obj, err := decodeObject(raw)
	if err != nil {
		return nil, err
	}
	for _, k := range []string{"schema_version", "image_version", "managed_environment", "python", "node", "features", "execution_supervisor"} {
		if _, ok := obj[k]; !ok {
			return nil, fmt.Errorf("%s: field required", k)
		}
	}
	sup := m.ExecutionSupervisor
	clean := path.Clean(sup.Path)
	switch {
	case m.SchemaVersion != 2:
		return nil, errors.New("schema_version: input should be 2")
	case m.ManagedEnvironment != "mutable" && m.ManagedEnvironment != "immutable":
		return nil, errors.New("managed_environment: input should be 'mutable' or 'immutable'")
	case m.Features.Browser != "none" && m.Features.Browser != "playwright":
		return nil, errors.New("features.browser: input should be 'none' or 'playwright'")
	case !isSHA256(sup.SHA256):
		return nil, errors.New("execution_supervisor.sha256: string should match pattern")
	case sup.ProtocolVersion != 1:
		return nil, errors.New("execution_supervisor.protocol_version: input should be 1")
	case sup.CommandUID <= 0 || sup.CommandGID <= 0:
		return nil, errors.New("execution_supervisor: command uid and gid must be greater than 0")
	case !strings.HasPrefix(sup.Path, "/") || clean != sup.Path || sup.Path == "/":
		return nil, errors.New("execution supervisor path must be an absolute clean file path")
	case m.Features.ManagedEnvironmentMutation != (m.ManagedEnvironment == "mutable"):
		return nil, errors.New("managed environment feature disagrees with profile")
	case !m.Features.ArbitraryWorkspaceCode:
		return nil, errors.New("runtime must disclose arbitrary workspace code capability")
	}
	if m.Tools == nil {
		m.Tools = map[string]string{}
	}
	if m.Packages == nil {
		m.Packages = map[string]string{}
	}
	return &m, nil
}
