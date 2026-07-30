package sandboxruntime

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

type Manager struct {
	provider  ExternalProvider
	store     *SessionStore
	leaseTTL  time.Duration
	manifests map[string]*runtimeinfo.Manifest
}

func NewManager(provider ExternalProvider, store *SessionStore, leaseTTL time.Duration, manifests map[string]*runtimeinfo.Manifest) (*Manager, error) {
	if provider == nil {
		return nil, fmt.Errorf("sandbox provider is required")
	}
	if store == nil {
		return nil, fmt.Errorf("sandbox session store is required")
	}
	if leaseTTL <= 0 {
		return nil, fmt.Errorf("sandbox task lease TTL must be positive")
	}
	for _, profile := range []string{runtimeinfo.PackageInstallAllowed, runtimeinfo.PackageInstallLocked} {
		if manifest := manifests[profile]; manifest != nil {
			if err := manifest.Validate(); err != nil {
				return nil, fmt.Errorf("%s runtime manifest: %w", profile, err)
			}
			if !manifest.SupportsPackageInstall(profile) {
				return nil, fmt.Errorf("%s runtime manifest does not enforce its declared profile", profile)
			}
		}
	}
	return &Manager{provider: provider, store: store, leaseTTL: leaseTTL, manifests: manifests}, nil
}

func (m *Manager) ExecuteSandbox(ctx context.Context, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	if req.WorkspaceID == "" || req.TaskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	if req.CommandBody == "" {
		return nil, fmt.Errorf("command_body is required")
	}
	session, err := m.ensure(ctx, req.WorkspaceID, req.TaskID, req.PackageInstall)
	if err != nil {
		return nil, err
	}
	result, err := m.executeWithHeartbeat(ctx, session, req)
	if errors.Is(err, ErrSessionNotFound) && !errors.Is(err, ErrExecutionHeartbeatFailed) {
		if deleteErr := m.store.DeleteIfSession(ctx, session); deleteErr != nil {
			return nil, deleteErr
		}
		session, err = m.ensure(ctx, req.WorkspaceID, req.TaskID, req.PackageInstall)
		if err != nil {
			return nil, err
		}
		result, err = m.executeWithHeartbeat(ctx, session, req)
	}
	if err != nil {
		return nil, err
	}
	if err := m.provider.Renew(ctx, session, m.leaseTTL); err != nil {
		return nil, fmt.Errorf("renew sandbox after execution: %w", err)
	}
	if err := m.recordLease(ctx, session, m.leaseTTL, true); err != nil {
		return nil, err
	}
	return result, nil
}

func (m *Manager) SandboxFilePut(ctx context.Context, req warmpool.FilePutRequest) (*warmpool.FilePutResponse, error) {
	if req.WorkspaceID == "" || req.TaskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	absolute, err := sandboxPath(req.Path)
	if err != nil {
		return nil, err
	}
	content, err := base64.StdEncoding.DecodeString(req.ContentBase64)
	if err != nil {
		return nil, fmt.Errorf("decode file content: %w", err)
	}
	if len(content) > maxSandboxFileBytes {
		return nil, fmt.Errorf("sandbox file exceeds 16 MiB upload limit")
	}
	session, err := m.ensure(ctx, req.WorkspaceID, req.TaskID, req.PackageInstall)
	if err != nil {
		return nil, err
	}
	if err := m.provider.PutFile(ctx, session, absolute, content); err != nil {
		if !errors.Is(err, ErrSessionNotFound) {
			return nil, err
		}
		if deleteErr := m.store.DeleteIfSession(ctx, session); deleteErr != nil {
			return nil, deleteErr
		}
		session, err = m.ensure(ctx, req.WorkspaceID, req.TaskID, req.PackageInstall)
		if err != nil {
			return nil, err
		}
		if err := m.provider.PutFile(ctx, session, absolute, content); err != nil {
			return nil, err
		}
	}
	return &warmpool.FilePutResponse{Path: req.Path, Size: len(content)}, nil
}

func (m *Manager) SandboxFileGet(ctx context.Context, workspaceID, taskID, filePath string) (*warmpool.FileGetResponse, error) {
	absolute, err := sandboxPath(filePath)
	if err != nil {
		return nil, err
	}
	session, err := m.existing(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	content, err := m.provider.GetFile(ctx, session, absolute)
	if errors.Is(err, ErrFileNotFound) {
		return nil, warmpool.ErrFileNotFound
	}
	if err != nil {
		return nil, err
	}
	return &warmpool.FileGetResponse{
		ContentBase64: base64.StdEncoding.EncodeToString(content),
		Size:          int64(len(content)),
	}, nil
}

func (m *Manager) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*warmpool.FileListResponse, error) {
	absolute := WorkspaceRoot
	if prefix != "" {
		var err error
		absolute, err = sandboxPath(prefix)
		if err != nil {
			return nil, err
		}
	}
	session, err := m.existing(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	paths, err := m.provider.ListFiles(ctx, session, absolute)
	if err != nil {
		return nil, err
	}
	relative := make([]string, 0, len(paths))
	for _, providerPath := range paths {
		item, err := relativeSandboxPath(providerPath)
		if err != nil {
			return nil, err
		}
		relative = append(relative, item)
	}
	return &warmpool.FileListResponse{Paths: relative}, nil
}

func (m *Manager) RuntimeManifest(_ context.Context, packageInstall string) (*runtimeinfo.Manifest, error) {
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, err
	}
	manifest := m.manifests[packageInstall]
	if manifest == nil {
		return nil, fmt.Errorf("sandbox provider %q has no configured %s runtime", m.provider.Name(), packageInstall)
	}
	copy := *manifest
	return &copy, nil
}

func (m *Manager) ListSandboxes(ctx context.Context, workspaceID string) ([]SandboxStatus, error) {
	if workspaceID == "" {
		return nil, fmt.Errorf("workspace_id is required")
	}
	lister, ok := m.provider.(ExternalSandboxLister)
	if !ok {
		return nil, fmt.Errorf("%w: provider %q does not expose live inventory", ErrInventoryUnavailable, m.provider.Name())
	}
	return lister.List(ctx, workspaceID)
}

func (m *Manager) RetireSandboxTask(ctx context.Context, taskID string, idleTTL time.Duration) error {
	session, err := m.store.Get(ctx, m.provider.Name(), taskID)
	if errors.Is(err, ErrSessionNotFound) {
		return nil
	}
	if err != nil {
		return err
	}
	if idleTTL > 0 {
		if err := m.provider.Renew(ctx, session, idleTTL); err != nil {
			if errors.Is(err, ErrSessionNotFound) {
				return m.store.DeleteIfSession(ctx, session)
			}
			return err
		}
		return m.recordLease(ctx, session, idleTTL, false)
	}
	if err := m.provider.Delete(ctx, session); err != nil && !errors.Is(err, ErrSessionNotFound) {
		return err
	}
	return m.store.Delete(ctx, m.provider.Name(), taskID)
}

func (m *Manager) ensure(ctx context.Context, workspaceID, taskID, packageInstall string) (*Session, error) {
	if err := runtimeinfo.ValidatePackageInstall(packageInstall); err != nil {
		return nil, err
	}
	if m.manifests[packageInstall] == nil {
		return nil, fmt.Errorf("sandbox provider %q does not offer package_install=%s", m.provider.Name(), packageInstall)
	}
	if session, err := m.store.Get(ctx, m.provider.Name(), taskID); err == nil {
		renewed, renewErr := m.renewExisting(ctx, session, workspaceID, packageInstall)
		if renewErr == nil {
			return renewed, nil
		}
		if !errors.Is(renewErr, ErrSessionNotFound) {
			return nil, renewErr
		}
		if err := m.store.DeleteIfSession(ctx, session); err != nil {
			return nil, err
		}
	} else if !errors.Is(err, ErrSessionNotFound) {
		return nil, err
	}

	var result *Session
	err := m.store.WithCreationLock(ctx, m.provider.Name(), taskID, func() error {
		if session, err := m.store.Get(ctx, m.provider.Name(), taskID); err == nil {
			var renewErr error
			result, renewErr = m.renewExisting(ctx, session, workspaceID, packageInstall)
			if renewErr == nil {
				return nil
			}
			if !errors.Is(renewErr, ErrSessionNotFound) {
				return renewErr
			}
			if err := m.store.DeleteIfSession(ctx, session); err != nil {
				return err
			}
		} else if !errors.Is(err, ErrSessionNotFound) {
			return err
		}

		session, err := m.provider.Create(ctx, CreateRequest{
			WorkspaceID:    workspaceID,
			TaskID:         taskID,
			PackageInstall: packageInstall,
		})
		if err != nil {
			return err
		}
		session.Provider = m.provider.Name()
		session.WorkspaceID = workspaceID
		session.TaskID = taskID
		session.PackageInstall = packageInstall
		if session.CreatedAt.IsZero() {
			session.CreatedAt = time.Now().UTC()
		}
		if session.LastUsedAt.IsZero() {
			session.LastUsedAt = session.CreatedAt
		}
		if session.ExpiresAt.IsZero() {
			session.ExpiresAt = session.LastUsedAt.Add(m.leaseTTL)
		}
		if err := m.store.Put(ctx, session); err != nil {
			_ = m.provider.Delete(context.Background(), session)
			return err
		}
		result = session
		return nil
	})
	return result, err
}

func (m *Manager) existing(ctx context.Context, workspaceID, taskID string) (*Session, error) {
	if workspaceID == "" || taskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	session, err := m.store.Get(ctx, m.provider.Name(), taskID)
	if err != nil {
		return nil, err
	}
	return m.renewExisting(ctx, session, workspaceID, session.PackageInstall)
}

func (m *Manager) renewExisting(ctx context.Context, session *Session, workspaceID, packageInstall string) (*Session, error) {
	if session.WorkspaceID != workspaceID {
		return nil, fmt.Errorf("task %q is already bound to another workspace", session.TaskID)
	}
	if session.PackageInstall != packageInstall {
		return nil, fmt.Errorf(
			"task %q is pinned to package_install=%s and cannot be weakened or moved to %s",
			session.TaskID, session.PackageInstall, packageInstall,
		)
	}
	if err := m.provider.Renew(ctx, session, m.leaseTTL); err != nil {
		return nil, err
	}
	if err := m.recordLease(ctx, session, m.leaseTTL, true); err != nil {
		return nil, err
	}
	return session, nil
}

func (m *Manager) recordLease(ctx context.Context, session *Session, ttl time.Duration, markUsed bool) error {
	now := time.Now().UTC()
	if markUsed || session.LastUsedAt.IsZero() {
		session.LastUsedAt = now
	}
	session.ExpiresAt = now.Add(ttl)
	return m.store.Put(ctx, session)
}

func (m *Manager) executeWithHeartbeat(ctx context.Context, session *Session, req warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	executionContext, cancelExecution := context.WithCancel(ctx)
	stopHeartbeat := make(chan struct{})
	heartbeatDone := make(chan error, 1)
	heartbeatInterval := m.leaseTTL / 3
	if heartbeatInterval <= 0 {
		heartbeatInterval = m.leaseTTL
	}

	go func() {
		ticker := time.NewTicker(heartbeatInterval)
		defer ticker.Stop()
		for {
			select {
			case <-stopHeartbeat:
				heartbeatDone <- nil
				return
			case <-ctx.Done():
				heartbeatDone <- ctx.Err()
				return
			case <-ticker.C:
				if err := m.provider.Renew(ctx, session, m.leaseTTL); err != nil {
					heartbeatDone <- err
					cancelExecution()
					return
				}
				if err := m.recordLease(ctx, session, m.leaseTTL, true); err != nil {
					heartbeatDone <- err
					cancelExecution()
					return
				}
			}
		}
	}()

	result, executionErr := m.provider.Execute(executionContext, session, req)
	close(stopHeartbeat)
	cancelExecution()
	if heartbeatErr := <-heartbeatDone; heartbeatErr != nil {
		return nil, fmt.Errorf("%w: %w", ErrExecutionHeartbeatFailed, heartbeatErr)
	}
	return result, executionErr
}
