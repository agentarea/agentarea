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
	"os"
	"sync"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
	"github.com/google/uuid"
)

// finalLeaseRenewTimeout bounds the last renewal issued once a download stream
// has been fully consumed. The request context is already finished by then, so
// the renewal needs its own deadline rather than an unbounded background one.
const finalLeaseRenewTimeout = 15 * time.Second

// providerCleanupTimeout bounds a best-effort teardown of a sandbox that has
// already lost its control-plane record.
const providerCleanupTimeout = 30 * time.Second

type Manager struct {
	provider            ExternalProvider
	store               *SessionStore
	activeLeaseTTL      time.Duration
	idleLeaseTTL        time.Duration
	manifest            *runtimeinfo.Manifest
	limits              WorkspaceLimits
	gate                *TaskOperationGate
	auditTTL            time.Duration
	cleanupTTL          time.Duration
	provisioningTimeout time.Duration
}

func NewManager(
	provider ExternalProvider,
	store *SessionStore,
	activeLeaseTTL time.Duration,
	idleLeaseTTL time.Duration,
	manifest *runtimeinfo.Manifest,
	limits WorkspaceLimits,
) (*Manager, error) {
	if provider == nil {
		return nil, fmt.Errorf("sandbox provider is required")
	}
	if store == nil {
		return nil, fmt.Errorf("sandbox session store is required")
	}
	if activeLeaseTTL <= 0 {
		return nil, fmt.Errorf("sandbox task lease TTL must be positive")
	}
	if idleLeaseTTL < 0 {
		return nil, fmt.Errorf("sandbox task idle TTL must be non-negative")
	}
	provisioningTimeout := provider.ProvisioningTimeout()
	if provisioningTimeout <= 0 {
		return nil, fmt.Errorf("sandbox provider provisioning timeout must be positive")
	}
	longestLease := activeLeaseTTL + provisioningTimeout
	if idleLeaseTTL > longestLease {
		longestLease = idleLeaseTTL
	}
	if store.ttl <= longestLease {
		return nil, fmt.Errorf("sandbox session record TTL must exceed active provisioning and idle lease windows")
	}
	if err := limits.Validate(); err != nil {
		return nil, err
	}
	if manifest == nil {
		return nil, fmt.Errorf("sandbox runtime manifest is required")
	}
	if err := manifest.Validate(); err != nil {
		return nil, fmt.Errorf("sandbox runtime manifest: %w", err)
	}
	return &Manager{
		provider:            provider,
		store:               store,
		activeLeaseTTL:      activeLeaseTTL,
		idleLeaseTTL:        idleLeaseTTL,
		manifest:            manifest,
		limits:              limits,
		gate:                NewDistributedTaskOperationGate(provider.Name(), store),
		auditTTL:            providerCleanupTimeout,
		cleanupTTL:          providerCleanupTimeout,
		provisioningTimeout: provisioningTimeout,
	}, nil
}

// enforceWorkspaceLimits measures the live workspace after an operation that
// can write outside the control-plane file API. A shell command can create a
// file the file API never admitted, so admission checks alone cannot hold the
// declared limits.
func (m *Manager) enforceWorkspaceLimits(ctx context.Context, session *Session) error {
	usage, err := m.provider.AuditWorkspace(ctx, session)
	if err != nil {
		return fmt.Errorf("audit sandbox workspace: %w", err)
	}
	return usage.Enforce(m.limits)
}

// discardUnsafeSession removes the exact provider binding whenever command
// quiescence or workspace safety cannot be proven. The quarantine tombstone is
// written before remote deletion so a failed cleanup cannot make the binding
// reusable. A changed binding is never deleted by identity confusion: the
// provider delete still targets the captured immutable session ID.
func (m *Manager) discardUnsafeSession(ctx context.Context, session *Session, cause error) error {
	quarantineCtx, cancelQuarantine := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	quarantined, quarantineErr := m.store.QuarantineIfSession(quarantineCtx, session)
	cancelQuarantine()
	if quarantineErr != nil {
		quarantineErr = fmt.Errorf("quarantine unsafe sandbox binding %s: %w", session.ID, quarantineErr)
	} else if !quarantined {
		quarantineErr = fmt.Errorf("quarantine unsafe sandbox binding %s: binding changed before quarantine", session.ID)
	}

	deleteCtx, cancelDelete := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	deleteErr := m.provider.Delete(deleteCtx, session)
	cancelDelete()
	if errors.Is(deleteErr, ErrSessionNotFound) {
		deleteErr = nil
	}
	if deleteErr != nil {
		deleteErr = fmt.Errorf("delete quarantined sandbox %s: %w", session.ID, deleteErr)
	}
	var clearErr error
	if quarantined && deleteErr == nil {
		clearCtx, cancelClear := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
		clearErr = m.store.ClearQuarantineIfSession(clearCtx, session)
		cancelClear()
		if clearErr != nil {
			clearErr = fmt.Errorf("clear deleted sandbox quarantine %s: %w", session.ID, clearErr)
		}
	}
	return errors.Join(cause, quarantineErr, deleteErr, clearErr)
}

// finalizeWorkspaceMutation audits even when the provider reports an error: a
// timed-out command or interrupted upload may already have changed the live
// filesystem. An unauditable or over-limit sandbox is removed from service and
// its exact binding is forgotten, so the next operation cannot reuse unsafe
// state. Cleanup uses a detached bounded context because the caller is commonly
// already cancelled in precisely the cases that need quarantine most.
func (m *Manager) finalizeWorkspaceMutation(ctx context.Context, session *Session, mutationErr error) error {
	auditCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.auditTTL)
	auditErr := m.enforceWorkspaceLimits(auditCtx, session)
	cancel()
	if auditErr == nil {
		return mutationErr
	}
	return m.discardUnsafeSession(ctx, session, errors.Join(mutationErr, auditErr))
}

// BeginOperation fences one unit of live sandbox work against retirement of the
// same binding. The returned context carries the fence, so a composing layer can
// hold it across several steps — workspace hydration followed by execution must
// be one fenced unit, or retirement lands between them and the command runs in a
// freshly created, unhydrated workspace. The returned release must run once the
// work — including any stream handed back to the caller — has finished.
func (m *Manager) BeginOperation(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	if workspaceID == "" || taskID == "" {
		return nil, nil, fmt.Errorf("workspace_id and task_id are required")
	}
	return m.gate.BeginOperation(ctx, workspaceID, taskID)
}

func (m *Manager) beginRetirement(ctx context.Context, workspaceID, taskID string) (context.Context, func(), error) {
	return m.gate.BeginRetirement(ctx, workspaceID, taskID)
}

func (m *Manager) ExecuteSandbox(ctx context.Context, req sandboxcontract.ExecuteRequest) (*sandboxcontract.ExecuteResponse, error) {
	if req.WorkspaceID == "" || req.TaskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	if req.CommandBody == "" {
		return nil, fmt.Errorf("command_body is required")
	}
	ctx, release, err := m.BeginOperation(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer release()
	session, err := m.ensure(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	result, err := m.executeWithHeartbeat(ctx, session, req)
	if errors.Is(err, ErrSessionNotFound) && !errors.Is(err, ErrExecutionHeartbeatFailed) {
		return nil, m.invalidateMissingSession(ctx, session, err)
	}
	if err != nil {
		auditCtx, cancelAudit := context.WithTimeout(context.WithoutCancel(ctx), m.auditTTL)
		auditErr := m.enforceWorkspaceLimits(auditCtx, session)
		cancelAudit()
		return nil, m.discardUnsafeSession(
			ctx,
			session,
			errors.Join(fmt.Errorf("sandbox execution did not prove quiescence: %w", err), auditErr),
		)
	}
	if renewErr := m.renewActive(ctx, session); renewErr != nil {
		return nil, m.discardUnsafeSession(ctx, session, fmt.Errorf("renew sandbox after execution: %w", renewErr))
	}
	if err := m.finalizeWorkspaceMutation(ctx, session, nil); err != nil {
		return nil, err
	}
	if err := m.transitionToIdle(ctx, session); err != nil {
		return nil, err
	}
	return result, nil
}

func (m *Manager) SandboxFilePut(ctx context.Context, req sandboxcontract.FilePutRequest) (*sandboxcontract.FilePutResponse, error) {
	if req.WorkspaceID == "" || req.TaskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	content, err := base64.StdEncoding.DecodeString(req.ContentBase64)
	if err != nil {
		return nil, fmt.Errorf("decode file content: %w", err)
	}
	if len(content) > maxInlineSandboxFileBytes {
		return nil, fmt.Errorf("sandbox file exceeds 16 MiB upload limit")
	}
	digest := sha256.Sum256(content)
	transfer := FileUpload{
		WorkspaceID: req.WorkspaceID, TaskID: req.TaskID,
		Path: req.Path, Size: int64(len(content)), SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}
	result, err := m.SandboxFileUpload(ctx, transfer, bytes.NewReader(content))
	if err != nil {
		return nil, err
	}
	return &sandboxcontract.FilePutResponse{Path: result.Path, Size: result.Size}, nil
}

func (m *Manager) SandboxFileUpload(ctx context.Context, req FileUpload, content io.Reader) (*FileWriteResult, error) {
	if req.WorkspaceID == "" || req.TaskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	if req.Size < 0 || !validSHA256(req.SHA256) || content == nil {
		return nil, fmt.Errorf("streamed sandbox file requires non-negative size, lowercase sha256, and content")
	}
	if req.Size > m.limits.MaxFileBytes {
		return nil, fmt.Errorf(
			"sandbox file of %d bytes exceeds the %d-byte per-file limit",
			req.Size, m.limits.MaxFileBytes,
		)
	}
	mode, err := normalizeFileMode(req.Mode)
	if err != nil {
		return nil, err
	}
	req.Mode = mode
	absolute, err := sandboxPath(req.Path)
	if err != nil {
		return nil, err
	}
	temp, err := os.CreateTemp("", "agentarea-provider-upload-*")
	if err != nil {
		return nil, fmt.Errorf("create verified upload spool: %w", err)
	}
	defer func() {
		_ = temp.Close()
		_ = os.Remove(temp.Name())
	}()
	hasher := sha256.New()
	written, err := io.Copy(io.MultiWriter(temp, hasher), io.LimitReader(content, req.Size+1))
	if err != nil {
		return nil, fmt.Errorf("spool sandbox upload: %w", err)
	}
	if written != req.Size || hex.EncodeToString(hasher.Sum(nil)) != req.SHA256 {
		return nil, fmt.Errorf("streamed sandbox file size or checksum mismatch")
	}
	if _, err := temp.Seek(0, io.SeekStart); err != nil {
		return nil, fmt.Errorf("rewind verified sandbox upload: %w", err)
	}
	ctx, release, err := m.BeginOperation(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	defer release()
	session, err := m.ensure(ctx, req.WorkspaceID, req.TaskID)
	if err != nil {
		return nil, err
	}
	providerReq := req
	providerReq.Path = absolute
	operationErr := m.runProviderOperation(ctx, session, func(operationCtx context.Context) error {
		return m.provider.PutFile(operationCtx, session, providerReq, temp)
	})
	if errors.Is(operationErr, ErrSessionNotFound) && !errors.Is(operationErr, ErrLeaseHeartbeatFailed) {
		return nil, m.invalidateMissingSession(ctx, session, operationErr)
	}
	if err := m.finalizeWorkspaceMutation(ctx, session, operationErr); err != nil {
		return nil, err
	}
	if err := m.transitionToIdle(ctx, session); err != nil {
		return nil, err
	}
	return &FileWriteResult{Path: req.Path, Size: req.Size}, nil
}

// invalidateMissingSession forgets both the binding and its hydration record.
// It deliberately does not execute the user's operation again: once a command
// reached a provider stream, the control plane cannot prove that retrying it is
// free of duplicate external side effects. The next demand restarts at the
// WorkspaceRuntime boundary and hydrates a replacement before doing any work.
func (m *Manager) invalidateMissingSession(ctx context.Context, session *Session, cause error) error {
	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	deleteErr := m.store.DeleteIfSession(cleanupCtx, session)
	cancel()
	if deleteErr != nil {
		return errors.Join(cause, fmt.Errorf("forget missing sandbox binding: %w", deleteErr))
	}
	return fmt.Errorf("%w: provider session %s disappeared: %v", ErrWorkspaceRehydration, session.ID, cause)
}

func (m *Manager) SandboxFileGet(ctx context.Context, workspaceID, taskID, filePath string) (*sandboxcontract.FileGetResponse, error) {
	download, err := m.SandboxFileDownload(ctx, workspaceID, taskID, filePath)
	if err != nil {
		return nil, err
	}
	defer download.Content.Close()
	if download.Size > maxInlineSandboxFileBytes {
		return nil, fmt.Errorf("sandbox file exceeds 16 MiB response limit; use the streamed file endpoint")
	}
	content, err := io.ReadAll(io.LimitReader(download.Content, maxInlineSandboxFileBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(content)) != download.Size {
		return nil, fmt.Errorf("sandbox file size changed during read")
	}
	return &sandboxcontract.FileGetResponse{
		ContentBase64: base64.StdEncoding.EncodeToString(content),
		Size:          int64(len(content)),
	}, nil
}

func (m *Manager) SandboxFileDownload(ctx context.Context, workspaceID, taskID, filePath string) (*FileDownload, error) {
	if workspaceID == "" || taskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	absolute, err := sandboxPath(filePath)
	if err != nil {
		return nil, err
	}
	// The read side is held until the returned stream is closed, so retirement
	// cannot delete the binding while bytes are still being served.
	ctx, release, err := m.BeginOperation(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	handedOff := false
	defer func() {
		if !handedOff {
			release()
		}
	}()
	session, err := m.existing(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	var download *FileDownload
	err = m.runProviderOperation(ctx, session, func(operationCtx context.Context) error {
		var operationErr error
		download, operationErr = m.provider.OpenFile(operationCtx, session, absolute)
		return operationErr
	})
	if errors.Is(err, ErrFileNotFound) {
		return nil, sandboxcontract.ErrFileNotFound
	}
	if err != nil {
		return nil, err
	}
	if download == nil || download.Content == nil || download.Size < 0 {
		if download != nil && download.Content != nil {
			download.Content.Close()
		}
		return nil, fmt.Errorf("sandbox provider returned an invalid file stream")
	}
	download.Content = newProviderLeaseReadCloser(ctx, download.Content, m, session, release)
	handedOff = true
	return download, nil
}

func (m *Manager) SandboxFileList(ctx context.Context, workspaceID, taskID, prefix string) (*sandboxcontract.FileListResponse, error) {
	if workspaceID == "" || taskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	absolute := WorkspaceRoot
	if prefix != "" {
		var err error
		absolute, err = sandboxPath(prefix)
		if err != nil {
			return nil, err
		}
	}
	ctx, release, err := m.BeginOperation(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	defer release()
	session, err := m.existing(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	var paths []string
	err = m.runProviderOperation(ctx, session, func(operationCtx context.Context) error {
		var operationErr error
		paths, operationErr = m.provider.ListFiles(operationCtx, session, absolute)
		return operationErr
	})
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
	if err := m.transitionToIdle(ctx, session); err != nil {
		return nil, err
	}
	return &sandboxcontract.FileListResponse{Paths: relative}, nil
}

func (m *Manager) RuntimeManifest(_ context.Context) (*runtimeinfo.Manifest, error) {
	copy := *m.manifest
	return &copy, nil
}

func (m *Manager) RetireSandboxTask(ctx context.Context, workspaceID, taskID string, idleTTL time.Duration) error {
	if workspaceID == "" || taskID == "" {
		return fmt.Errorf("workspace_id and task_id are required")
	}
	// Retirement waits for every in-flight command, upload, listing and
	// download stream on this binding before it can renew or delete it.
	ctx, release, err := m.beginRetirement(ctx, workspaceID, taskID)
	if err != nil {
		return err
	}
	defer release()
	session, err := m.store.Get(ctx, m.provider.Name(), workspaceID, taskID)
	if errors.Is(err, ErrSessionQuarantined) {
		session, err = m.store.GetQuarantined(ctx, m.provider.Name(), workspaceID, taskID)
		if err != nil {
			return err
		}
		if deleteErr := m.provider.Delete(ctx, session); deleteErr != nil && !errors.Is(deleteErr, ErrSessionNotFound) {
			return deleteErr
		}
		return m.store.ClearQuarantineIfSession(ctx, session)
	}
	if errors.Is(err, ErrSessionNotFound) {
		return m.store.WithCreationLock(ctx, m.provider.Name(), workspaceID, taskID, func(lockCtx context.Context, lock taskLock) error {
			intent, intentErr := m.store.getProvisioning(lockCtx, m.provider.Name(), workspaceID, taskID)
			if errors.Is(intentErr, ErrSessionNotFound) {
				return nil
			}
			if intentErr != nil {
				return intentErr
			}
			return m.reconcilePendingProvisioning(lockCtx, lock, *intent)
		})
	}
	if err != nil {
		return err
	}
	if session.WorkspaceID != workspaceID {
		return fmt.Errorf("sandbox session workspace mismatch")
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
	return m.store.Delete(ctx, m.provider.Name(), workspaceID, taskID)
}

type managerWithInventory struct {
	*Manager
	lister ExternalSandboxLister
}

func (m *managerWithInventory) ListSandboxes(ctx context.Context, workspaceID string) ([]SandboxStatus, error) {
	if workspaceID == "" {
		return nil, fmt.Errorf("workspace_id is required")
	}
	return m.lister.List(ctx, workspaceID)
}

var _ SandboxLister = (*managerWithInventory)(nil)

func (m *Manager) EnsureWorkspaceHydrated(
	ctx context.Context,
	workspaceID, taskID, revision string,
	hydrate func(context.Context) error,
) error {
	if hydrate == nil || !validSHA256(revision) {
		return fmt.Errorf("workspace hydration requires a callback and a valid revision")
	}
	if workspaceID == "" || taskID == "" {
		return fmt.Errorf("workspace_id and task_id are required")
	}
	ctx, release, err := m.BeginOperation(ctx, workspaceID, taskID)
	if err != nil {
		return err
	}
	defer release()
	if _, err := m.ensure(ctx, workspaceID, taskID); err != nil {
		return err
	}
	return m.store.withTaskLock(ctx, m.provider.Name(), workspaceID, taskID, "hydration", func(lockCtx context.Context, lock taskLock) error {
		session, err := m.store.Get(lockCtx, m.provider.Name(), workspaceID, taskID)
		if err != nil {
			return err
		}
		if _, err := m.renewExisting(lockCtx, session, workspaceID); err != nil {
			if errors.Is(err, ErrSessionNotFound) {
				return m.invalidateMissingSession(lockCtx, session, err)
			}
			return err
		}
		record, err := m.store.getHydration(lockCtx, session)
		if err != nil {
			return err
		}
		if record != nil && record.SessionID == session.ID {
			if record.WorkspaceID != workspaceID {
				return fmt.Errorf("stored sandbox hydration identity is inconsistent")
			}
			if record.Revision == revision {
				return nil
			}
			return fmt.Errorf("live sandbox is hydrated from revision %s and cannot be mutated to %s", record.Revision, revision)
		}
		if err := hydrate(lockCtx); err != nil {
			return err
		}
		return m.store.putHydrationIfSession(lockCtx, session, hydrationRecord{
			SessionID: session.ID, WorkspaceID: workspaceID,
			Revision: revision,
		}, lock)
	})
}

func (m *Manager) ensure(ctx context.Context, workspaceID, taskID string) (*Session, error) {
	if session, err := m.store.Get(ctx, m.provider.Name(), workspaceID, taskID); err == nil {
		renewed, renewErr := m.renewExisting(ctx, session, workspaceID)
		if renewErr == nil {
			return renewed, nil
		}
		if !errors.Is(renewErr, ErrSessionNotFound) {
			return nil, renewErr
		}
		if err := m.store.DeleteIfSession(ctx, session); err != nil {
			return nil, err
		}
		return nil, fmt.Errorf(
			"%w: provider session %s disappeared during demand admission",
			ErrWorkspaceRehydration,
			session.ID,
		)
	} else if !errors.Is(err, ErrSessionNotFound) {
		return nil, err
	}

	var result *Session
	err := m.store.WithCreationLock(ctx, m.provider.Name(), workspaceID, taskID, func(lockCtx context.Context, lock taskLock) error {
		if session, err := m.store.Get(lockCtx, m.provider.Name(), workspaceID, taskID); err == nil {
			var renewErr error
			result, renewErr = m.renewExisting(lockCtx, session, workspaceID)
			if renewErr == nil {
				return nil
			}
			if !errors.Is(renewErr, ErrSessionNotFound) {
				return renewErr
			}
			if err := m.store.DeleteIfSession(lockCtx, session); err != nil {
				return err
			}
			return fmt.Errorf(
				"%w: provider session %s disappeared during serialized demand admission",
				ErrWorkspaceRehydration,
				session.ID,
			)
		} else if !errors.Is(err, ErrSessionNotFound) {
			return err
		}

		pending, pendingErr := m.store.getProvisioning(lockCtx, m.provider.Name(), workspaceID, taskID)
		if pendingErr == nil {
			if err := m.reconcilePendingProvisioning(lockCtx, lock, *pending); err != nil {
				return err
			}
		} else if !errors.Is(pendingErr, ErrSessionNotFound) {
			return pendingErr
		}

		now := time.Now().UTC()
		intent := ProvisioningIntent{
			Provider:       m.provider.Name(),
			ProvisioningID: uuid.NewString(),
			WorkspaceID:    workspaceID,
			TaskID:         taskID,
			StartedAt:      now,
			ExpiresAt:      now.Add(m.provisioningTimeout + m.activeLeaseTTL),
		}
		if err := m.store.beginProvisioningIfLockOwned(lockCtx, intent, lock); err != nil {
			return err
		}
		createCtx, cancelCreate := context.WithTimeout(lockCtx, m.provisioningTimeout)
		session, err := m.provider.Create(createCtx, CreateRequest{
			WorkspaceID:    workspaceID,
			TaskID:         taskID,
			ProvisioningID: intent.ProvisioningID,
			Supervisor:     m.manifest.ExecutionSupervisor,
		})
		cancelCreate()
		if session == nil || session.ID == "" {
			if err == nil {
				err = fmt.Errorf("%s returned no sandbox identity", m.provider.Name())
			}
			return errors.Join(err, m.reconcilePendingProvisioning(lockCtx, lock, intent))
		}
		if err != nil {
			m.bindSessionIdentity(session, workspaceID, taskID)
			return errors.Join(err, m.cleanupFailedProvisioning(lockCtx, lock, intent, session))
		}
		m.bindSessionIdentity(session, workspaceID, taskID)
		if err := m.store.putProvisioningIfLockOwned(lockCtx, session, intent, lock); err != nil {
			return errors.Join(err, m.cleanupFailedProvisioning(lockCtx, lock, intent, session))
		}
		result = session
		return nil
	})
	return result, err
}

func (m *Manager) bindSessionIdentity(session *Session, workspaceID, taskID string) {
	if session == nil {
		return
	}
	session.Provider = m.provider.Name()
	session.WorkspaceID = workspaceID
	session.TaskID = taskID
	if session.CreatedAt.IsZero() {
		session.CreatedAt = time.Now().UTC()
	}
	if session.LastUsedAt.IsZero() {
		session.LastUsedAt = session.CreatedAt
	}
	if session.ExpiresAt.IsZero() {
		session.ExpiresAt = session.LastUsedAt.Add(m.activeLeaseTTL)
	}
}

func (m *Manager) cleanupFailedProvisioning(
	ctx context.Context,
	lock taskLock,
	intent ProvisioningIntent,
	session *Session,
) error {
	if session.ID == "" {
		return fmt.Errorf("provider returned a failed provisioning without a sandbox identity")
	}
	recordCtx, cancelRecord := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	recordErr := m.store.quarantineProvisioningIfLockOwned(recordCtx, session, intent, lock)
	cancelRecord()
	if recordErr != nil {
		cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
		deleteErr := m.provider.Delete(cleanupCtx, session)
		cancel()
		if errors.Is(deleteErr, ErrSessionNotFound) {
			deleteErr = nil
		}
		return errors.Join(recordErr, deleteErr)
	}

	cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	deleteErr := m.provider.Delete(cleanupCtx, session)
	cancel()
	if errors.Is(deleteErr, ErrSessionNotFound) {
		deleteErr = nil
	}
	if deleteErr != nil {
		return fmt.Errorf("delete failed provisioning sandbox %s: %w", session.ID, deleteErr)
	}
	clearCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	clearErr := m.store.ClearQuarantineIfSession(clearCtx, session)
	cancel()
	if clearErr != nil {
		return fmt.Errorf("clear failed provisioning quarantine %s: %w", session.ID, clearErr)
	}
	return nil
}

// reconcilePendingProvisioning resolves a create whose HTTP outcome was lost.
// The durable intent itself is the fail-closed tombstone and can represent more
// than one provider resource if a remote API violated request uniqueness. An
// empty inventory result is trusted only after the requested remote lease has
// expired; before that, eventual visibility could still reveal an allocation.
func (m *Manager) reconcilePendingProvisioning(
	ctx context.Context,
	lock taskLock,
	intent ProvisioningIntent,
) error {
	reconcileCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	sessions, resolveErr := m.provider.ResolveProvisioning(reconcileCtx, intent)
	cancel()
	if resolveErr != nil {
		return errors.Join(
			ErrProvisioningUnresolved,
			fmt.Errorf("resolve %s provisioning %s: %w", m.provider.Name(), intent.ProvisioningID, resolveErr),
		)
	}
	seen := make(map[string]struct{}, len(sessions))
	var deleteErrs []error
	for _, session := range sessions {
		if session == nil || session.ID == "" {
			deleteErrs = append(deleteErrs, fmt.Errorf("provider returned an invalid provisioning match"))
			continue
		}
		if _, duplicate := seen[session.ID]; duplicate {
			deleteErrs = append(deleteErrs, fmt.Errorf("provider returned duplicate provisioning match %s", session.ID))
			continue
		}
		seen[session.ID] = struct{}{}
		m.bindSessionIdentity(session, intent.WorkspaceID, intent.TaskID)
		deleteCtx, cancelDelete := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
		deleteErr := m.provider.Delete(deleteCtx, session)
		cancelDelete()
		if deleteErr != nil && !errors.Is(deleteErr, ErrSessionNotFound) {
			deleteErrs = append(deleteErrs, fmt.Errorf("delete unresolved sandbox %s: %w", session.ID, deleteErr))
		}
	}
	if err := errors.Join(deleteErrs...); err != nil {
		return errors.Join(ErrProvisioningUnresolved, err)
	}
	if len(sessions) > 0 {
		return fmt.Errorf(
			"%w: removed %d provisioning match(es) for %s; a clean inventory pass is required after %s",
			ErrProvisioningUnresolved,
			len(sessions),
			intent.ProvisioningID,
			intent.ExpiresAt.Format(time.RFC3339),
		)
	}
	if time.Now().UTC().Before(intent.ExpiresAt) {
		return fmt.Errorf(
			"%w: provisioning %s remains fenced until the allocation visibility window closes at %s",
			ErrProvisioningUnresolved, intent.ProvisioningID, intent.ExpiresAt.Format(time.RFC3339),
		)
	}
	clearCtx, cancelClear := context.WithTimeout(context.WithoutCancel(ctx), m.cleanupTTL)
	clearErr := m.store.clearProvisioningIfLockOwned(clearCtx, intent, lock)
	cancelClear()
	if clearErr != nil {
		return errors.Join(ErrProvisioningUnresolved, clearErr)
	}
	return nil
}

func (m *Manager) existing(ctx context.Context, workspaceID, taskID string) (*Session, error) {
	if workspaceID == "" || taskID == "" {
		return nil, fmt.Errorf("workspace_id and task_id are required")
	}
	session, err := m.store.Get(ctx, m.provider.Name(), workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	return m.renewExisting(ctx, session, workspaceID)
}

func (m *Manager) renewExisting(ctx context.Context, session *Session, workspaceID string) (*Session, error) {
	if session.WorkspaceID != workspaceID {
		return nil, fmt.Errorf("task %q is already bound to another workspace", session.TaskID)
	}
	if err := m.renewActive(ctx, session); err != nil {
		return nil, err
	}
	return session, nil
}

func (m *Manager) renewActive(ctx context.Context, session *Session) error {
	if err := m.provider.Renew(ctx, session, m.activeLeaseTTL); err != nil {
		return err
	}
	return m.recordLease(ctx, session, m.activeLeaseTTL, true)
}

func (m *Manager) transitionToIdle(ctx context.Context, session *Session) error {
	idleCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), finalLeaseRenewTimeout)
	defer cancel()
	if m.idleLeaseTTL == 0 {
		if err := m.provider.Delete(idleCtx, session); err != nil && !errors.Is(err, ErrSessionNotFound) {
			return fmt.Errorf("delete sandbox after operation: %w", err)
		}
		return m.store.DeleteIfSession(idleCtx, session)
	}
	if err := m.provider.Renew(idleCtx, session, m.idleLeaseTTL); err != nil {
		if errors.Is(err, ErrSessionNotFound) {
			return m.invalidateMissingSession(idleCtx, session, err)
		}
		return fmt.Errorf("set sandbox idle lease: %w", err)
	}
	return m.recordLease(idleCtx, session, m.idleLeaseTTL, false)
}

func (m *Manager) recordLease(ctx context.Context, session *Session, ttl time.Duration, markUsed bool) error {
	now := time.Now().UTC()
	if markUsed || session.LastUsedAt.IsZero() {
		session.LastUsedAt = now
	}
	session.ExpiresAt = now.Add(ttl)
	return m.store.Put(ctx, session)
}

func (m *Manager) executeWithHeartbeat(ctx context.Context, session *Session, req sandboxcontract.ExecuteRequest) (*sandboxcontract.ExecuteResponse, error) {
	executionContext, cancelExecution := context.WithCancel(ctx)
	stopHeartbeat := make(chan struct{})
	heartbeatDone := make(chan error, 1)
	heartbeatInterval := m.activeLeaseTTL / 3
	if heartbeatInterval <= 0 {
		heartbeatInterval = m.activeLeaseTTL
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
				if err := m.provider.Renew(ctx, session, m.activeLeaseTTL); err != nil {
					heartbeatDone <- err
					cancelExecution()
					return
				}
				if err := m.recordLease(ctx, session, m.activeLeaseTTL, true); err != nil {
					heartbeatDone <- err
					cancelExecution()
					return
				}
			}
		}
	}()

	result, executionErr := m.provider.ExecuteQuiescent(executionContext, session, QuiescentExecution{
		Request: req, Supervisor: m.manifest.ExecutionSupervisor, MaxFileBytes: m.limits.MaxFileBytes,
	})
	close(stopHeartbeat)
	cancelExecution()
	if heartbeatErr := <-heartbeatDone; heartbeatErr != nil {
		return nil, fmt.Errorf("%w: %w", ErrExecutionHeartbeatFailed, heartbeatErr)
	}
	return result, executionErr
}

func (m *Manager) runProviderOperation(ctx context.Context, session *Session, operation func(context.Context) error) error {
	operationCtx, cancel := context.WithCancel(ctx)
	stop := make(chan struct{})
	done := make(chan error, 1)
	go m.leaseHeartbeat(operationCtx, session, stop, done, cancel, nil)
	operationErr := operation(operationCtx)
	close(stop)
	heartbeatErr := <-done
	cancel()
	if heartbeatErr != nil {
		return fmt.Errorf("%w: %w", ErrLeaseHeartbeatFailed, heartbeatErr)
	}
	if operationErr != nil {
		return operationErr
	}
	if err := m.renewActive(ctx, session); err != nil {
		return fmt.Errorf("renew sandbox after provider operation: %w", err)
	}
	return nil
}

func (m *Manager) leaseHeartbeat(
	ctx context.Context,
	session *Session,
	stop <-chan struct{},
	done chan<- error,
	cancel context.CancelFunc,
	closer io.Closer,
) {
	interval := m.activeLeaseTTL / 3
	if interval <= 0 {
		interval = m.activeLeaseTTL
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-stop:
			done <- nil
			return
		case <-ctx.Done():
			if errors.Is(ctx.Err(), context.Canceled) {
				done <- nil
			} else {
				done <- ctx.Err()
			}
			return
		case <-ticker.C:
			if err := m.provider.Renew(ctx, session, m.activeLeaseTTL); err != nil {
				if closer != nil {
					_ = closer.Close()
				}
				cancel()
				done <- err
				return
			}
			if err := m.recordLease(ctx, session, m.activeLeaseTTL, true); err != nil {
				if closer != nil {
					_ = closer.Close()
				}
				cancel()
				done <- err
				return
			}
		}
	}
}

type providerLeaseReadCloser struct {
	source    io.ReadCloser
	manager   *Manager
	session   *Session
	parentCtx context.Context
	cancel    context.CancelFunc
	release   func()
	stop      chan struct{}
	done      chan error
	stopOnce  sync.Once
	stopErr   error
}

func newProviderLeaseReadCloser(
	ctx context.Context,
	source io.ReadCloser,
	manager *Manager,
	session *Session,
	release func(),
) io.ReadCloser {
	leaseCtx, cancel := context.WithCancel(ctx)
	reader := &providerLeaseReadCloser{
		source: source, manager: manager, session: session,
		parentCtx: ctx, cancel: cancel, release: release,
		stop: make(chan struct{}), done: make(chan error, 1),
	}
	go manager.leaseHeartbeat(leaseCtx, session, reader.stop, reader.done, cancel, source)
	return reader
}

func (r *providerLeaseReadCloser) Read(buffer []byte) (int, error) {
	n, err := r.source.Read(buffer)
	if err != nil {
		r.finish()
		if r.stopErr != nil {
			return n, fmt.Errorf("%w: %w", ErrLeaseHeartbeatFailed, r.stopErr)
		}
	}
	return n, err
}

func (r *providerLeaseReadCloser) Close() error {
	sourceErr := r.source.Close()
	r.finish()
	if r.stopErr != nil {
		return fmt.Errorf("%w: %w", ErrLeaseHeartbeatFailed, r.stopErr)
	}
	return sourceErr
}

// finish stops the heartbeat, then — only when the stream ended cleanly under a
// live caller context — issues one bounded final renewal so the binding carries
// the configured idle lease. The renewal must happen before
// cancel(), and the operation lock is released last so retirement cannot
// observe the binding as idle while the renewal is still in flight.
func (r *providerLeaseReadCloser) finish() {
	r.stopOnce.Do(func() {
		close(r.stop)
		r.stopErr = <-r.done
		if r.stopErr == nil && r.parentCtx.Err() == nil {
			renewCtx, cancelRenew := context.WithTimeout(context.WithoutCancel(r.parentCtx), finalLeaseRenewTimeout)
			r.stopErr = r.manager.transitionToIdle(renewCtx, r.session)
			cancelRenew()
		}
		r.cancel()
		if r.release != nil {
			r.release()
		}
	})
}
