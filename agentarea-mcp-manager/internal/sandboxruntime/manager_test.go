package sandboxruntime

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
)

type fakeExternalProvider struct {
	mu           sync.Mutex
	creates      int
	renews       int
	deletes      int
	executeIDs   []string
	files        map[string][]byte
	renewErr     error
	executeErr   error
	putErr       error
	executeDelay time.Duration
}

func (p *fakeExternalProvider) Name() string { return "fake" }

func (p *fakeExternalProvider) Create(_ context.Context, _ CreateRequest) (*Session, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.creates++
	return &Session{ID: "sandbox-" + string(rune('0'+p.creates))}, nil
}

func (p *fakeExternalProvider) Renew(_ context.Context, _ *Session, _ time.Duration) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.renews++
	err := p.renewErr
	p.renewErr = nil
	return err
}

func (p *fakeExternalProvider) Execute(ctx context.Context, session *Session, _ warmpool.ExecuteRequest) (*warmpool.ExecuteResponse, error) {
	p.mu.Lock()
	p.executeIDs = append(p.executeIDs, session.ID)
	delay := p.executeDelay
	err := p.executeErr
	p.executeErr = nil
	p.mu.Unlock()
	if err != nil {
		return nil, err
	}
	if delay > 0 {
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(delay):
		}
	}
	return &warmpool.ExecuteResponse{ExitCode: 0}, nil
}

func (p *fakeExternalProvider) PutFile(_ context.Context, _ *Session, path string, content []byte) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.putErr != nil {
		err := p.putErr
		p.putErr = nil
		return err
	}
	if p.files == nil {
		p.files = make(map[string][]byte)
	}
	p.files[path] = append([]byte(nil), content...)
	return nil
}

func (p *fakeExternalProvider) GetFile(_ context.Context, _ *Session, path string) ([]byte, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	content, ok := p.files[path]
	if !ok {
		return nil, ErrFileNotFound
	}
	return append([]byte(nil), content...), nil
}

func (p *fakeExternalProvider) ListFiles(_ context.Context, _ *Session, prefix string) ([]string, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	var result []string
	for filePath := range p.files {
		if len(filePath) >= len(prefix) && filePath[:len(prefix)] == prefix {
			result = append(result, filePath)
		}
	}
	return result, nil
}

func (p *fakeExternalProvider) Delete(_ context.Context, _ *Session) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.deletes++
	return nil
}

func (p *fakeExternalProvider) List(_ context.Context, workspaceID string) ([]SandboxStatus, error) {
	return []SandboxStatus{{
		ID:          "sandbox-live",
		Provider:    p.Name(),
		WorkspaceID: workspaceID,
		State:       "running",
	}}, nil
}

func TestManagerPinsFilesAndExecutionsToOneProviderSession(t *testing.T) {
	manager, provider := newTestManager(t)
	ctx := context.Background()

	_, err := manager.SandboxFilePut(ctx, warmpool.FilePutRequest{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		Path:           "inputs/data.txt",
		ContentBase64:  "aGVsbG8=",
	})
	if err != nil {
		t.Fatalf("SandboxFilePut() error = %v", err)
	}
	_, err = manager.ExecuteSandbox(ctx, warmpool.ExecuteRequest{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		CommandBody:    "cat inputs/data.txt",
	})
	if err != nil {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}

	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 1 {
		t.Fatalf("creates = %d, want 1", provider.creates)
	}
	if len(provider.executeIDs) != 1 || provider.executeIDs[0] != "sandbox-1" {
		t.Fatalf("execute sessions = %v, want sandbox-1", provider.executeIDs)
	}
	if got := string(provider.files["/workspace/inputs/data.txt"]); got != "hello" {
		t.Fatalf("staged file = %q, want hello", got)
	}
}

func TestManagerListsOnlyProviderLiveInventory(t *testing.T) {
	manager, _ := newTestManager(t)
	items, err := manager.ListSandboxes(context.Background(), "workspace-1")
	if err != nil {
		t.Fatalf("ListSandboxes() error = %v", err)
	}
	if len(items) != 1 || items[0].WorkspaceID != "workspace-1" || items[0].State != "running" {
		t.Fatalf("ListSandboxes() = %+v", items)
	}
}

func TestManagerRejectsRuntimeProfileChangeForLiveTask(t *testing.T) {
	manager, _ := newTestManager(t)
	ctx := context.Background()
	request := warmpool.ExecuteRequest{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		CommandBody:    "true",
	}
	if _, err := manager.ExecuteSandbox(ctx, request); err != nil {
		t.Fatalf("first ExecuteSandbox() error = %v", err)
	}
	request.PackageInstall = runtimeinfo.PackageInstallLocked
	if _, err := manager.ExecuteSandbox(ctx, request); err == nil {
		t.Fatal("profile change unexpectedly succeeded")
	}
}

func TestManagerRecreatesOnlyWhenPinnedProviderReportsExpired(t *testing.T) {
	manager, provider := newTestManager(t)
	ctx := context.Background()
	request := warmpool.ExecuteRequest{
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		CommandBody:    "true",
	}
	if _, err := manager.ExecuteSandbox(ctx, request); err != nil {
		t.Fatalf("first ExecuteSandbox() error = %v", err)
	}
	provider.renewErr = ErrSessionNotFound
	if _, err := manager.ExecuteSandbox(ctx, request); err != nil {
		t.Fatalf("recreated ExecuteSandbox() error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 {
		t.Fatalf("creates = %d, want 2", provider.creates)
	}
	if got := provider.executeIDs[len(provider.executeIDs)-1]; got != "sandbox-2" {
		t.Fatalf("last execution session = %s, want sandbox-2", got)
	}
}

func TestManagerRetriesOnceWhenSessionExpiresBetweenRenewAndExecution(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.executeErr = ErrSessionNotFound
	if _, err := manager.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed, CommandBody: "true",
	}); err != nil {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 {
		t.Fatalf("creates = %d, want one replacement", provider.creates)
	}
	if got := provider.executeIDs[len(provider.executeIDs)-1]; got != "sandbox-2" {
		t.Fatalf("last execution session = %s, want sandbox-2", got)
	}
}

func TestManagerRetriesFilePutOnceWhenSessionExpiresAfterRenew(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.putErr = ErrSessionNotFound
	if _, err := manager.SandboxFilePut(context.Background(), warmpool.FilePutRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed,
		Path:           "input.txt", ContentBase64: "aGVsbG8=",
	}); err != nil {
		t.Fatalf("SandboxFilePut() error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 {
		t.Fatalf("creates = %d, want one replacement", provider.creates)
	}
	if got := string(provider.files["/workspace/input.txt"]); got != "hello" {
		t.Fatalf("staged file = %q", got)
	}
}

func TestManagerFileReadDoesNotCreateMissingSession(t *testing.T) {
	manager, provider := newTestManager(t)
	_, err := manager.SandboxFileGet(context.Background(), "workspace-1", "task-1", "missing.txt")
	if !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("SandboxFileGet() error = %v, want ErrSessionNotFound", err)
	}
	if provider.creates != 0 {
		t.Fatalf("creates = %d, want 0", provider.creates)
	}
}

func TestManagerRetireUsesProviderTTLUnlessForced(t *testing.T) {
	manager, provider := newTestManager(t)
	ctx := context.Background()
	if _, err := manager.ExecuteSandbox(ctx, warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed, CommandBody: "true",
	}); err != nil {
		t.Fatal(err)
	}
	if err := manager.RetireSandboxTask(ctx, "task-1", time.Minute); err != nil {
		t.Fatalf("RetireSandboxTask(idle) error = %v", err)
	}
	if err := manager.RetireSandboxTask(ctx, "task-1", 0); err != nil {
		t.Fatalf("RetireSandboxTask(force) error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.deletes != 1 {
		t.Fatalf("deletes = %d, want 1", provider.deletes)
	}
}

func TestManagerKeepsLongExecutionAliveAndRenewsFromCompletion(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:heartbeat", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	provider := &fakeExternalProvider{executeDelay: 80 * time.Millisecond}
	manager, err := NewManager(provider, store, 30*time.Millisecond, map[string]*runtimeinfo.Manifest{
		runtimeinfo.PackageInstallAllowed: testManifest(true),
	})
	if err != nil {
		t.Fatal(err)
	}

	if _, err := manager.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed, CommandBody: "sleep",
	}); err != nil {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}

	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.renews < 2 {
		t.Fatalf("renews = %d, want heartbeat plus completion renewal", provider.renews)
	}
}

func TestManagerDoesNotRetryCommandAfterHeartbeatLosesSession(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:heartbeat-loss", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	provider := &fakeExternalProvider{
		executeDelay: 80 * time.Millisecond,
		renewErr:     ErrSessionNotFound,
	}
	manager, err := NewManager(provider, store, 30*time.Millisecond, map[string]*runtimeinfo.Manifest{
		runtimeinfo.PackageInstallAllowed: testManifest(true),
	})
	if err != nil {
		t.Fatal(err)
	}

	_, err = manager.ExecuteSandbox(context.Background(), warmpool.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		PackageInstall: runtimeinfo.PackageInstallAllowed, CommandBody: "sleep",
	})
	if !errors.Is(err, ErrExecutionHeartbeatFailed) {
		t.Fatalf("ExecuteSandbox() error = %v, want heartbeat failure", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 1 {
		t.Fatalf("creates = %d, command was retried after an unknown execution outcome", provider.creates)
	}
}

func TestSessionStoreStaleDeleteCannotRemoveReplacement(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:cas", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	stale := &Session{Provider: "fake", ID: "old", TaskID: "task-1", WorkspaceID: "workspace-1"}
	replacement := &Session{Provider: "fake", ID: "new", TaskID: "task-1", WorkspaceID: "workspace-1"}
	if err := store.Put(context.Background(), stale); err != nil {
		t.Fatal(err)
	}
	if err := store.Put(context.Background(), replacement); err != nil {
		t.Fatal(err)
	}
	if err := store.DeleteIfSession(context.Background(), stale); err != nil {
		t.Fatal(err)
	}
	stored, err := store.Get(context.Background(), "fake", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if stored.ID != "new" {
		t.Fatalf("stored session = %q, want replacement", stored.ID)
	}
}

func newTestManager(t *testing.T) (*Manager, *fakeExternalProvider) {
	t.Helper()
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:sandbox", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	provider := &fakeExternalProvider{}
	manager, err := NewManager(provider, store, 15*time.Minute, map[string]*runtimeinfo.Manifest{
		runtimeinfo.PackageInstallAllowed: testManifest(true),
		runtimeinfo.PackageInstallLocked:  testManifest(false),
	})
	if err != nil {
		t.Fatal(err)
	}
	return manager, provider
}

func testManifest(mutable bool) *runtimeinfo.Manifest {
	environment := "immutable"
	if mutable {
		environment = "mutable"
	}
	return &runtimeinfo.Manifest{
		SchemaVersion:      1,
		ImageVersion:       environment + "-test",
		ManagedEnvironment: environment,
		Python:             runtimeinfo.PythonRuntime{Version: "3.12", Executable: "/usr/bin/python3"},
		Node:               runtimeinfo.NodeRuntime{Version: "v22"},
		Tools:              map[string]string{},
		Packages:           map[string]string{},
		Features: runtimeinfo.Features{
			Browser:                    "none",
			ManagedEnvironmentMutation: mutable,
			ArbitraryWorkspaceCode:     true,
		},
	}
}
