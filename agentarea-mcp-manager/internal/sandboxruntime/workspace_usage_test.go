package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
)

func TestShellCreatedOversizeWorkspaceIsRejectedAfterExecution(t *testing.T) {
	manager, provider := newTestManager(t)
	limits := testWorkspaceLimits()
	provider.mu.Lock()
	provider.usage = &WorkspaceUsage{Entries: 1, LargestBytes: 1, TotalBytes: limits.MaxBytes + 1}
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "dd if=/dev/zero of=big",
	})
	if err == nil || !strings.Contains(err.Error(), "policy allows") {
		t.Fatalf("ExecuteSandbox() error = %v, want a workspace limit violation", err)
	}
	if provider.auditCount() == 0 {
		t.Fatal("workspace was never audited after a shell command")
	}
	assertSandboxQuarantined(t, manager, provider)
}

func TestShellCreatedOversizeFileIsRejectedAfterExecution(t *testing.T) {
	manager, provider := newTestManager(t)
	limits := testWorkspaceLimits()
	provider.mu.Lock()
	provider.usage = &WorkspaceUsage{Entries: 1, LargestBytes: limits.MaxFileBytes + 1, TotalBytes: limits.MaxFileBytes + 1}
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "per file") {
		t.Fatalf("ExecuteSandbox() error = %v, want a per-file limit violation", err)
	}
}

func TestShellCreatedFileCountIsRejectedAfterExecution(t *testing.T) {
	manager, provider := newTestManager(t)
	limits := testWorkspaceLimits()
	provider.mu.Lock()
	provider.usage = &WorkspaceUsage{Entries: limits.MaxFiles + 1, LargestBytes: 1, TotalBytes: int64(limits.MaxFiles + 1)}
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "files") {
		t.Fatalf("ExecuteSandbox() error = %v, want a file-count limit violation", err)
	}
}

func TestUploadRejectsFileLargerThanPerFileLimitBeforeSpooling(t *testing.T) {
	manager, provider := newTestManager(t)
	limits := testWorkspaceLimits()
	digest := sha256.Sum256(nil)
	_, err := manager.SandboxFileUpload(context.Background(), FileUpload{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "big.bin", Size: limits.MaxFileBytes + 1,
		SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, strings.NewReader(""))
	if err == nil || !strings.Contains(err.Error(), "per-file limit") {
		t.Fatalf("SandboxFileUpload() error = %v, want a per-file limit rejection", err)
	}
	if provider.creates != 0 {
		t.Fatal("an oversized upload reached the provider")
	}
}

func TestAuditFailureFailsTheOperationClosed(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.auditErr = context.DeadlineExceeded
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "audit sandbox workspace") {
		t.Fatalf("ExecuteSandbox() error = %v, want the unauditable workspace to fail closed", err)
	}
	assertSandboxQuarantined(t, manager, provider)
}

func TestAuditTimeoutStillQuarantinesWithIndependentCleanupDeadline(t *testing.T) {
	manager, provider := newTestManager(t)
	manager.auditTTL = 20 * time.Millisecond
	manager.cleanupTTL = time.Second
	provider.mu.Lock()
	provider.auditDelay = 200 * time.Millisecond
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "deadline exceeded") {
		t.Fatalf("ExecuteSandbox() error = %v, want audit deadline failure", err)
	}
	assertSandboxQuarantined(t, manager, provider)
}

func TestFailedQuarantineDeleteLeavesTaskTombstonedUntilRetirementRetries(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.auditErr = context.DeadlineExceeded
	provider.deleteErr = errors.New("provider unavailable")
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "provider unavailable") {
		t.Fatalf("ExecuteSandbox() error = %v, want quarantine cleanup failure", err)
	}
	if _, err := manager.store.Get(context.Background(), provider.Name(), "workspace-1", "task-1"); !errors.Is(err, ErrSessionQuarantined) {
		t.Fatalf("unsafe binding error = %v, want ErrSessionQuarantined", err)
	}
	provider.mu.Lock()
	createsBeforeRetry := provider.creates
	provider.auditErr = nil
	provider.mu.Unlock()
	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}); !errors.Is(err, ErrSessionQuarantined) {
		t.Fatalf("execution against tombstoned task error = %v, want ErrSessionQuarantined", err)
	}
	provider.mu.Lock()
	createsAfterRetry := provider.creates
	provider.mu.Unlock()
	if createsAfterRetry != createsBeforeRetry {
		t.Fatal("tombstoned task created a replacement beside an orphan")
	}
	if err := manager.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err != nil {
		t.Fatalf("RetireSandboxTask() quarantine retry error = %v", err)
	}
	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}); err != nil {
		t.Fatalf("execution after quarantine cleanup error = %v", err)
	}
}

func TestFailedExecutionStillAuditsAndQuarantinesAnOversizeWorkspace(t *testing.T) {
	manager, provider := newTestManager(t)
	limits := testWorkspaceLimits()
	provider.mu.Lock()
	provider.executeErr = context.DeadlineExceeded
	provider.usage = &WorkspaceUsage{Entries: 1, LargestBytes: 1, TotalBytes: limits.MaxBytes + 1}
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "partially-write-then-timeout",
	})
	if err == nil || !strings.Contains(err.Error(), "deadline exceeded") || !strings.Contains(err.Error(), "policy allows") {
		t.Fatalf("ExecuteSandbox() error = %v, want execution and workspace-limit failures", err)
	}
	if provider.auditCount() == 0 {
		t.Fatal("failed execution skipped the workspace audit")
	}
	assertSandboxQuarantined(t, manager, provider)
}

func TestUncertainExecutionDeletesBindingEvenWhenWorkspaceAuditIsClean(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.executeErr = errors.New("execution supervisor status was missing")
	provider.usage = &WorkspaceUsage{Entries: 1, LargestBytes: 1, TotalBytes: 1}
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "background-command",
	})
	if err == nil || !strings.Contains(err.Error(), "did not prove quiescence") {
		t.Fatalf("ExecuteSandbox() error = %v, want quiescence failure", err)
	}
	if provider.auditCount() == 0 {
		t.Fatal("uncertain execution skipped the bounded workspace audit")
	}
	assertSandboxQuarantined(t, manager, provider)
}

func TestFailedUploadStillAuditsAndQuarantinesAnOversizeWorkspace(t *testing.T) {
	manager, provider := newTestManager(t)
	limits := testWorkspaceLimits()
	content := []byte("partial")
	digest := sha256.Sum256(content)
	provider.mu.Lock()
	provider.putErr = context.DeadlineExceeded
	provider.usage = &WorkspaceUsage{Entries: 1, LargestBytes: 1, TotalBytes: limits.MaxBytes + 1}
	provider.mu.Unlock()

	_, err := manager.SandboxFileUpload(context.Background(), FileUpload{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "partial.bin", Size: int64(len(content)),
		SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, bytes.NewReader(content))
	if err == nil || !strings.Contains(err.Error(), "deadline exceeded") || !strings.Contains(err.Error(), "policy allows") {
		t.Fatalf("SandboxFileUpload() error = %v, want upload and workspace-limit failures", err)
	}
	if provider.auditCount() == 0 {
		t.Fatal("failed upload skipped the workspace audit")
	}
	assertSandboxQuarantined(t, manager, provider)
}

func assertSandboxQuarantined(t *testing.T, manager *Manager, provider *fakeExternalProvider) {
	t.Helper()
	if provider.deleteCount() != 1 {
		t.Fatalf("provider deletes = %d, want the unsafe sandbox quarantined", provider.deleteCount())
	}
	_, err := manager.store.Get(context.Background(), provider.Name(), "workspace-1", "task-1")
	if !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("quarantined sandbox binding error = %v, want ErrSessionNotFound", err)
	}
}

func TestWorkspaceLimitsMustBeDeclaredAndCoherent(t *testing.T) {
	for name, limits := range map[string]WorkspaceLimits{
		"undeclared":       {},
		"no file count":    {MaxFiles: 0, MaxFileBytes: 10, MaxBytes: 100},
		"no per-file cap":  {MaxFiles: 10, MaxFileBytes: 0, MaxBytes: 100},
		"total below file": {MaxFiles: 10, MaxFileBytes: 100, MaxBytes: 10},
	} {
		t.Run(name, func(t *testing.T) {
			if err := limits.Validate(); err == nil {
				t.Fatalf("limits %+v unexpectedly accepted", limits)
			}
		})
	}
	if err := testWorkspaceLimits().Validate(); err != nil {
		t.Fatalf("coherent limits rejected: %v", err)
	}
}

func TestWorkspaceAuditWalksProviderFilesystemWithoutGuestCommands(t *testing.T) {
	entries := map[string][]workspaceEntry{
		WorkspaceRoot: {
			{Path: WorkspaceRoot + "/input.txt", Kind: workspaceEntryFile, Size: 5},
			{Path: WorkspaceRoot + "/nested", Kind: workspaceEntryDirectory},
		},
		WorkspaceRoot + "/nested": {
			{Path: WorkspaceRoot + "/nested/result.bin", Kind: workspaceEntryFile, Size: 12},
			{Path: WorkspaceRoot + "/nested/link", Kind: workspaceEntrySymlink, Size: 4},
		},
	}
	var listed []string
	usage, err := auditWorkspaceFilesystem(
		context.Background(),
		"provider",
		WorkspaceRoot,
		func(_ context.Context, directory string) ([]workspaceEntry, error) {
			listed = append(listed, directory)
			return entries[directory], nil
		},
	)
	if err != nil {
		t.Fatalf("auditWorkspaceFilesystem() error = %v", err)
	}
	if usage != (WorkspaceUsage{Entries: 4, TotalBytes: 21, LargestBytes: 12}) {
		t.Fatalf("auditWorkspaceFilesystem() = %+v", usage)
	}
	if strings.Join(listed, ",") != WorkspaceRoot+","+WorkspaceRoot+"/nested" {
		t.Fatalf("listed directories = %v", listed)
	}
}

func TestWorkspaceAuditRejectsUntrustedProviderMetadata(t *testing.T) {
	tests := map[string]workspaceEntry{
		"outside root":  {Path: "/etc/passwd", Kind: workspaceEntryFile, Size: 1},
		"skipped depth": {Path: WorkspaceRoot + "/nested/file", Kind: workspaceEntryFile, Size: 1},
		"negative size": {Path: WorkspaceRoot + "/file", Kind: workspaceEntryFile, Size: -1},
		"unknown type":  {Path: WorkspaceRoot + "/file", Size: 1},
	}
	for name, entry := range tests {
		t.Run(name, func(t *testing.T) {
			_, err := auditWorkspaceFilesystem(
				context.Background(),
				"provider",
				WorkspaceRoot,
				func(context.Context, string) ([]workspaceEntry, error) { return []workspaceEntry{entry}, nil },
			)
			if err == nil {
				t.Fatal("invalid filesystem metadata unexpectedly accepted")
			}
		})
	}
}
