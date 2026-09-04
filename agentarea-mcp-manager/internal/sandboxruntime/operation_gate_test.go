package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
)

const fenceObservationWindow = 100 * time.Millisecond

func newFencingManager(t *testing.T, leaseTTL time.Duration) (*Manager, *fakeExternalProvider) {
	t.Helper()
	managers, provider := newFencingManagers(t, leaseTTL, 1)
	return managers[0], provider
}

func newFencingManagers(t *testing.T, leaseTTL time.Duration, count int) ([]*Manager, *fakeExternalProvider) {
	t.Helper()
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:fencing", leaseTTL+time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	provider := &fakeExternalProvider{}
	managers := make([]*Manager, 0, count)
	for range count {
		manager, err := NewManager(provider, store, leaseTTL, time.Minute, testManifest(), testWorkspaceLimits())
		if err != nil {
			t.Fatal(err)
		}
		managers = append(managers, manager)
	}
	return managers, provider
}

func fencingExecuteRequest() sandboxcontract.ExecuteRequest {
	return sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		CommandBody: "true",
	}
}

func stageFencingFile(t *testing.T, manager *Manager, content []byte) {
	t.Helper()
	digest := sha256.Sum256(content)
	if _, err := manager.SandboxFileUpload(context.Background(), FileUpload{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "result.txt", Size: int64(len(content)),
		SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, bytes.NewReader(content)); err != nil {
		t.Fatalf("stage sandbox file: %v", err)
	}
}

func TestRetirementWaitsForInFlightCommand(t *testing.T) {
	manager, provider := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()
	entered := make(chan struct{}, 1)
	provider.mu.Lock()
	provider.executeEntered = entered
	provider.executeDelay = 250 * time.Millisecond
	provider.mu.Unlock()

	executed := make(chan error, 1)
	go func() {
		_, err := manager.ExecuteSandbox(ctx, fencingExecuteRequest())
		executed <- err
	}()
	<-entered

	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()

	select {
	case err := <-retired:
		t.Fatalf("retirement completed while a command was still running (err = %v)", err)
	case <-time.After(fenceObservationWindow):
	}

	if err := <-executed; err != nil {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}
	if err := <-retired; err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}

	events := provider.recordedEvents()
	deleteIndex := slices.Index(events, "delete")
	endIndex := slices.Index(events, "execute-end")
	if deleteIndex < 0 || endIndex < 0 || deleteIndex < endIndex {
		t.Fatalf("provider events = %v, want the delete strictly after execute-end", events)
	}
}

// The API manager and the standalone runner build independent Manager values.
// A process-local mutex therefore cannot protect an OpenSandbox binding: both
// processes must coordinate through the shared SessionStore.
func TestRetirementOnAnotherManagerWaitsForInFlightCommand(t *testing.T) {
	managers, provider := newFencingManagers(t, 15*time.Minute, 2)
	commandManager, retirementManager := managers[0], managers[1]
	ctx := context.Background()
	entered := make(chan struct{}, 1)
	provider.mu.Lock()
	provider.executeEntered = entered
	provider.executeDelay = 250 * time.Millisecond
	provider.mu.Unlock()

	executed := make(chan error, 1)
	go func() {
		_, err := commandManager.ExecuteSandbox(ctx, fencingExecuteRequest())
		executed <- err
	}()
	<-entered

	retired := make(chan error, 1)
	go func() { retired <- retirementManager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()

	select {
	case err := <-retired:
		t.Fatalf("cross-manager retirement completed while a command was still running (err = %v)", err)
	case <-time.After(fenceObservationWindow):
	}
	if err := <-executed; err != nil {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}
	if err := <-retired; err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}

	events := provider.recordedEvents()
	deleteIndex := slices.Index(events, "delete")
	endIndex := slices.Index(events, "execute-end")
	if deleteIndex < 0 || endIndex < 0 || deleteIndex < endIndex {
		t.Fatalf("provider events = %v, want the cross-manager delete strictly after execute-end", events)
	}
}

func TestRetirementWaitsForOpenDownloadStream(t *testing.T) {
	manager, provider := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()
	stageFencingFile(t, manager, []byte("streamed-body"))

	download, err := manager.SandboxFileDownload(ctx, "workspace-1", "task-1", "result.txt")
	if err != nil {
		t.Fatalf("SandboxFileDownload() error = %v", err)
	}

	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()

	select {
	case err := <-retired:
		t.Fatalf("retirement completed while a download stream was still open (err = %v)", err)
	case <-time.After(fenceObservationWindow):
	}

	if provider.deleteCount() != 0 {
		t.Fatal("provider workload was deleted underneath an open download stream")
	}
	if _, err := io.ReadAll(download.Content); err != nil {
		t.Fatalf("read streamed download: %v", err)
	}
	if err := download.Content.Close(); err != nil {
		t.Fatalf("close streamed download: %v", err)
	}
	if err := <-retired; err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}
	if provider.deleteCount() != 1 {
		t.Fatalf("provider deletes = %d, want 1 after the stream closed", provider.deleteCount())
	}
}

func TestPendingRetirementBlocksNewOperations(t *testing.T) {
	manager, provider := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()
	entered := make(chan struct{}, 1)
	provider.mu.Lock()
	provider.executeEntered = entered
	provider.executeDelay = 300 * time.Millisecond
	provider.mu.Unlock()

	firstExecuted := make(chan error, 1)
	go func() {
		_, err := manager.ExecuteSandbox(ctx, fencingExecuteRequest())
		firstExecuted <- err
	}()
	<-entered

	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()
	time.Sleep(30 * time.Millisecond)

	secondExecuted := make(chan error, 1)
	go func() {
		_, err := manager.ExecuteSandbox(ctx, fencingExecuteRequest())
		secondExecuted <- err
	}()

	select {
	case err := <-secondExecuted:
		t.Fatalf("a new command overtook a waiting retirement (err = %v)", err)
	case <-time.After(fenceObservationWindow):
	}

	if err := <-firstExecuted; err != nil {
		t.Fatalf("first ExecuteSandbox() error = %v", err)
	}
	if err := <-retired; err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}
	if err := <-secondExecuted; err != nil {
		t.Fatalf("second ExecuteSandbox() error = %v", err)
	}

	events := provider.recordedEvents()
	deleteIndex := slices.Index(events, "delete")
	lastStart := slices.Index(events[deleteIndex:], "execute-start")
	if deleteIndex < 0 || lastStart < 0 {
		t.Fatalf("provider events = %v, want the second command to start after the delete", events)
	}
}

func TestFailedOperationReleasesRetirementFence(t *testing.T) {
	manager, provider := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()
	if _, err := manager.ExecuteSandbox(ctx, fencingExecuteRequest()); err != nil {
		t.Fatalf("initial ExecuteSandbox() error = %v", err)
	}

	provider.mu.Lock()
	provider.executeErr = errors.New("sandbox command rejected")
	provider.mu.Unlock()
	if _, err := manager.ExecuteSandbox(ctx, fencingExecuteRequest()); err == nil {
		t.Fatal("failing ExecuteSandbox() unexpectedly succeeded")
	}

	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()
	select {
	case err := <-retired:
		if err != nil {
			t.Fatalf("RetireSandboxTask() error = %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("a failed command left the retirement fence held")
	}
}

func TestFailedDownloadReleasesRetirementFence(t *testing.T) {
	manager, _ := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()
	if _, err := manager.ExecuteSandbox(ctx, fencingExecuteRequest()); err != nil {
		t.Fatalf("initial ExecuteSandbox() error = %v", err)
	}
	if _, err := manager.SandboxFileDownload(ctx, "workspace-1", "task-1", "missing.txt"); !errors.Is(err, sandboxcontract.ErrFileNotFound) {
		t.Fatalf("SandboxFileDownload() error = %v, want ErrFileNotFound", err)
	}

	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()
	select {
	case err := <-retired:
		if err != nil {
			t.Fatalf("RetireSandboxTask() error = %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("a failed download left the retirement fence held")
	}
}

// A lease TTL far longer than the test keeps the heartbeat from ever ticking,
// so the only renewal that can follow the read is the deliberate final one.
func TestStreamedDownloadIssuesFinalLeaseRenewal(t *testing.T) {
	manager, provider := newFencingManager(t, time.Hour)
	ctx := context.Background()
	stageFencingFile(t, manager, []byte("final-renewal"))

	provider.mu.Lock()
	provider.renews = 0
	provider.mu.Unlock()

	download, err := manager.SandboxFileDownload(ctx, "workspace-1", "task-1", "result.txt")
	if err != nil {
		t.Fatalf("SandboxFileDownload() error = %v", err)
	}
	renewsAfterOpen := provider.renewCount()
	if _, err := io.ReadAll(download.Content); err != nil {
		t.Fatalf("read streamed download: %v", err)
	}
	if err := download.Content.Close(); err != nil {
		t.Fatalf("close streamed download: %v", err)
	}
	if got := provider.renewCount(); got <= renewsAfterOpen {
		t.Fatalf("provider renewals after the stream finished = %d, want more than %d", got, renewsAfterOpen)
	}
}

func TestStreamedDownloadSkipsFinalRenewalWhenCallerContextEnded(t *testing.T) {
	manager, provider := newFencingManager(t, time.Hour)
	stageFencingFile(t, manager, []byte("abandoned"))

	ctx, cancel := context.WithCancel(context.Background())
	download, err := manager.SandboxFileDownload(ctx, "workspace-1", "task-1", "result.txt")
	if err != nil {
		t.Fatalf("SandboxFileDownload() error = %v", err)
	}
	provider.mu.Lock()
	provider.renews = 0
	provider.mu.Unlock()
	cancel()
	if err := download.Content.Close(); err != nil {
		t.Fatalf("close streamed download: %v", err)
	}
	if got := provider.renewCount(); got != 0 {
		t.Fatalf("provider renewals after an abandoned stream = %d, want 0", got)
	}
	// The fence must still be released even though no renewal was issued.
	if err := manager.RetireSandboxTask(context.Background(), "workspace-1", "task-1", 0); err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}
}

func TestOperationGateRejectsAcquisitionWhenCallerContextEnds(t *testing.T) {
	gate := newOperationGate()
	key := gateKey("fake", "workspace-1", "task-1")
	releaseWriter, err := gate.acquire(context.Background(), key, true)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if _, err := gate.acquire(ctx, key, false); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("acquire() error = %v, want DeadlineExceeded", err)
	}
	releaseWriter()

	release, err := gate.acquire(context.Background(), key, false)
	if err != nil {
		t.Fatalf("acquire() after abandoned waiter error = %v", err)
	}
	release()

	// Every reservation, including the abandoned one, must eventually drain.
	deadline := time.Now().Add(2 * time.Second)
	for {
		gate.mu.Lock()
		remaining := len(gate.entries)
		gate.mu.Unlock()
		if remaining == 0 {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("operation gate retained %d entries after every holder released", remaining)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// TestCompositeOperationHoldsOneFenceAcrossHydrationAndExecution closes the
// window between the two calls a workspace-backed execution makes. Fencing each
// step separately is not enough: a retirement arriving in the gap deletes the
// hydrated binding, and the command then runs in a freshly created empty one.
func TestCompositeOperationHoldsOneFenceAcrossHydrationAndExecution(t *testing.T) {
	manager, provider := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()

	outerCtx, release, err := manager.BeginOperation(ctx, "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}

	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()
	select {
	case err := <-retired:
		t.Fatalf("retirement ran inside a held composite fence (err = %v)", err)
	case <-time.After(fenceObservationWindow):
	}

	// The inner step re-enters with the fenced context and must not block on the
	// pending writer — it is already inside the fence its caller holds.
	inner := make(chan error, 1)
	go func() {
		_, err := manager.ExecuteSandbox(outerCtx, fencingExecuteRequest())
		inner <- err
	}()
	select {
	case err := <-inner:
		if err != nil {
			t.Fatalf("inner step under a held fence failed: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("inner step deadlocked re-acquiring a fence its caller already held")
	}

	release()
	if err := <-retired; err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}

	events := provider.recordedEvents()
	deleteIndex := slices.Index(events, "delete")
	endIndex := slices.Index(events, "execute-end")
	if deleteIndex < 0 || endIndex < 0 || deleteIndex < endIndex {
		t.Fatalf("provider events = %v, want the delete strictly after the fenced work", events)
	}
}

// TestRetirementInsideAHeldFenceIsRejectedNotDeadlocked keeps a wiring mistake
// loud: taking the write side while the same goroutine holds the read side
// would otherwise hang the process forever.
func TestRetirementInsideAHeldFenceIsRejectedNotDeadlocked(t *testing.T) {
	manager, _ := newFencingManager(t, 15*time.Minute)
	fenced, release, err := manager.BeginOperation(context.Background(), "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	defer release()

	done := make(chan error, 1)
	go func() { done <- manager.RetireSandboxTask(fenced, "workspace-1", "task-1", 0) }()
	select {
	case err := <-done:
		if err == nil || !strings.Contains(err.Error(), "cannot run inside a live operation") {
			t.Fatalf("RetireSandboxTask() error = %v, want an explicit rejection", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("retirement inside a held fence deadlocked instead of failing loudly")
	}
}

// TestUngatedRuntimeRefusesToFenceKeeps an incompletely assembled runtime from
// running unfenced work: without a gate there is nothing holding retirement off.
func TestUngatedRuntimeRefusesToFence(t *testing.T) {
	var missing *TaskOperationGate
	if _, _, err := missing.BeginOperation(context.Background(), "workspace-1", "task-1"); err == nil {
		t.Fatal("a runtime without an operation gate silently ran unfenced")
	}
	if _, _, err := missing.BeginRetirement(context.Background(), "workspace-1", "task-1"); err == nil {
		t.Fatal("a runtime without an operation gate silently retired unfenced")
	}
	empty := &TaskOperationGate{provider: "fake"}
	if _, _, err := empty.BeginOperation(context.Background(), "workspace-1", "task-1"); err == nil {
		t.Fatal("a zero-valued operation gate silently ran unfenced")
	}
}

// TestReleasedFenceMarkerStopsCounting keeps a context from outliving the fence
// it refers to. Reusing a released context must take a real fence again, not be
// waved through with a no-op release and run unfenced.
func TestReleasedFenceMarkerStopsCounting(t *testing.T) {
	manager, _ := newFencingManager(t, 15*time.Minute)
	ctx := context.Background()

	key := gateKey("fake", "workspace-1", "task-1")

	fenced, release, err := manager.BeginOperation(ctx, "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if !fenceHeld(fenced, key) {
		t.Fatal("a live fence was not recorded on the context")
	}
	release()

	if fenceHeld(fenced, key) {
		t.Fatal("a released fence marker still reports the fence as held; reusing it would run unfenced")
	}

	// Reusing the stale context must take a real fence again — provable by the
	// fact that retirement then has to wait for it.
	reused, reusedRelease, err := manager.BeginOperation(fenced, "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if !fenceHeld(reused, key) {
		t.Fatal("re-entering with a stale context did not take a fresh fence")
	}
	retired := make(chan error, 1)
	go func() { retired <- manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0) }()
	select {
	case err := <-retired:
		t.Fatalf("retirement ran while the re-taken fence was held (err = %v)", err)
	case <-time.After(fenceObservationWindow):
	}
	reusedRelease()
	if err := <-retired; err != nil {
		t.Fatalf("RetireSandboxTask() error = %v", err)
	}
}
