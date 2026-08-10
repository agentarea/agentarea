package sandboxruntime

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	redis "github.com/go-redis/redis/v8"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/sandboxcontract"
)

type fakeExternalProvider struct {
	mu                       sync.Mutex
	creates                  int
	renews                   int
	renewTTLs                []time.Duration
	puts                     int
	deletes                  int
	executeIDs               []string
	files                    map[string][]byte
	createErr                error
	createReturnsNil         bool
	createAllocatedOnError   bool
	createWaitsForCancel     bool
	createEntered            chan struct{}
	resolveErr               error
	provisioned              map[string][]*Session
	renewErr                 error
	renewErrOn               int
	executeErr               error
	putErr                   error
	deleteErr                error
	executeDelay             time.Duration
	readDelay                time.Duration
	streamBoundToOpenContext bool
	executeEntered           chan struct{}
	events                   []string
	usage                    *WorkspaceUsage
	auditErr                 error
	auditDelay               time.Duration
	audits                   int
}

func (p *fakeExternalProvider) Name() string { return "fake" }

func (p *fakeExternalProvider) ProvisioningTimeout() time.Duration { return 30 * time.Second }

func (p *fakeExternalProvider) record(event string) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.events = append(p.events, event)
}

func (p *fakeExternalProvider) recordedEvents() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]string(nil), p.events...)
}

func (p *fakeExternalProvider) deleteCount() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.deletes
}

func (p *fakeExternalProvider) renewCount() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.renews
}

func (p *fakeExternalProvider) Create(ctx context.Context, req CreateRequest) (*Session, error) {
	p.mu.Lock()
	p.creates++
	session := &Session{ID: "sandbox-" + string(rune('0'+p.creates))}
	err := p.createErr
	p.createErr = nil
	returnsNil := p.createReturnsNil
	waitsForCancel := p.createWaitsForCancel
	entered := p.createEntered
	if waitsForCancel || (err != nil && returnsNil && p.createAllocatedOnError) {
		if p.provisioned == nil {
			p.provisioned = make(map[string][]*Session)
		}
		p.provisioned[req.ProvisioningID] = append(p.provisioned[req.ProvisioningID], session)
	}
	p.mu.Unlock()
	if entered != nil {
		select {
		case entered <- struct{}{}:
		default:
		}
	}
	if waitsForCancel {
		<-ctx.Done()
		if err == nil {
			err = ctx.Err()
		}
	}
	if err != nil && returnsNil {
		return nil, err
	}
	return session, err
}

func (p *fakeExternalProvider) ResolveProvisioning(_ context.Context, intent ProvisioningIntent) ([]*Session, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.resolveErr != nil {
		return nil, p.resolveErr
	}
	matches := p.provisioned[intent.ProvisioningID]
	result := make([]*Session, 0, len(matches))
	for _, session := range matches {
		copy := *session
		result = append(result, &copy)
	}
	return result, nil
}

func (p *fakeExternalProvider) Renew(_ context.Context, _ *Session, ttl time.Duration) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.renews++
	p.renewTTLs = append(p.renewTTLs, ttl)
	if p.renewErrOn > 0 && p.renews == p.renewErrOn {
		return ErrSessionNotFound
	}
	err := p.renewErr
	p.renewErr = nil
	return err
}

func (p *fakeExternalProvider) ExecuteQuiescent(ctx context.Context, session *Session, _ QuiescentExecution) (*sandboxcontract.ExecuteResponse, error) {
	p.mu.Lock()
	p.executeIDs = append(p.executeIDs, session.ID)
	p.events = append(p.events, "execute-start")
	delay := p.executeDelay
	err := p.executeErr
	p.executeErr = nil
	entered := p.executeEntered
	p.mu.Unlock()
	if entered != nil {
		select {
		case entered <- struct{}{}:
		default:
		}
	}
	if err != nil {
		p.record("execute-end")
		return nil, err
	}
	if delay > 0 {
		select {
		case <-ctx.Done():
			p.record("execute-end")
			return nil, ctx.Err()
		case <-time.After(delay):
		}
	}
	p.record("execute-end")
	return &sandboxcontract.ExecuteResponse{ExitCode: 0}, nil
}

func (p *fakeExternalProvider) PutFile(_ context.Context, _ *Session, transfer FileUpload, source io.Reader) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.puts++
	if p.putErr != nil {
		err := p.putErr
		p.putErr = nil
		return err
	}
	if p.files == nil {
		p.files = make(map[string][]byte)
	}
	content, err := io.ReadAll(source)
	if err != nil {
		return err
	}
	p.files[transfer.Path] = content
	return nil
}

func (p *fakeExternalProvider) OpenFile(ctx context.Context, _ *Session, path string) (*FileDownload, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	stored, ok := p.files[path]
	if !ok {
		return nil, ErrFileNotFound
	}
	copy := append([]byte(nil), stored...)
	var content io.ReadCloser = io.NopCloser(bytes.NewReader(copy))
	if p.readDelay > 0 {
		content = &slowReadCloser{content: copy, delay: p.readDelay}
	}
	if p.streamBoundToOpenContext {
		// A real provider serves the file as the body of the request opened here,
		// so reads fail once that request's context is done.
		content = &contextBoundReadCloser{source: content, ctx: ctx}
	}
	return &FileDownload{Content: content, Size: int64(len(copy)), Mode: 0o600}, nil
}

type contextBoundReadCloser struct {
	source io.ReadCloser
	ctx    context.Context
}

func (r *contextBoundReadCloser) Read(buffer []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	return r.source.Read(buffer)
}

func (r *contextBoundReadCloser) Close() error { return r.source.Close() }

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

func (p *fakeExternalProvider) Delete(_ context.Context, session *Session) error {
	return p.deleteSession(session)
}

func (p *fakeExternalProvider) deleteSession(session *Session) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.deletes++
	p.events = append(p.events, "delete")
	if p.deleteErr != nil {
		err := p.deleteErr
		p.deleteErr = nil
		return err
	}
	for provisioningID, sessions := range p.provisioned {
		kept := sessions[:0]
		for _, candidate := range sessions {
			if session == nil || candidate.ID != session.ID {
				kept = append(kept, candidate)
			}
		}
		if len(kept) == 0 {
			delete(p.provisioned, provisioningID)
		} else {
			p.provisioned[provisioningID] = kept
		}
	}
	return nil
}

// AuditWorkspace reports the live workspace shape. It defaults to the files the
// fake actually holds so limit enforcement is exercised on real state.
func (p *fakeExternalProvider) AuditWorkspace(ctx context.Context, _ *Session) (WorkspaceUsage, error) {
	p.mu.Lock()
	delay := p.auditDelay
	p.mu.Unlock()
	if delay > 0 {
		select {
		case <-ctx.Done():
			return WorkspaceUsage{}, ctx.Err()
		case <-time.After(delay):
		}
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	p.audits++
	if p.auditErr != nil {
		return WorkspaceUsage{}, p.auditErr
	}
	if p.usage != nil {
		return *p.usage, nil
	}
	usage := WorkspaceUsage{}
	for _, content := range p.files {
		usage.Entries++
		usage.TotalBytes += int64(len(content))
		if int64(len(content)) > usage.LargestBytes {
			usage.LargestBytes = int64(len(content))
		}
	}
	return usage, nil
}

func (p *fakeExternalProvider) auditCount() int {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.audits
}

func TestManagerOwnsCleanupAfterProviderPostCreateFailure(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.createErr = errors.New("runtime attestation failed")
	provider.deleteErr = errors.New("provider cleanup unavailable")
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "runtime attestation failed") || !strings.Contains(err.Error(), "provider cleanup unavailable") {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}
	quarantined, err := manager.store.GetQuarantined(context.Background(), provider.Name(), "workspace-1", "task-1")
	if err != nil {
		t.Fatalf("GetQuarantined() error = %v", err)
	}
	if quarantined.ID != "sandbox-1" {
		t.Fatalf("quarantined provisioning = %+v", quarantined)
	}
	provider.mu.Lock()
	creates := provider.creates
	provider.mu.Unlock()
	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}); !errors.Is(err, ErrSessionQuarantined) {
		t.Fatalf("second execution error = %v, want ErrSessionQuarantined", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != creates {
		t.Fatal("manager created a replacement beside failed provisioning")
	}
}

func TestManagerClearsProvisioningTombstoneAfterSuccessfulCompensation(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.createErr = errors.New("runtime attestation failed")
	provider.mu.Unlock()

	_, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	})
	if err == nil || !strings.Contains(err.Error(), "runtime attestation failed") {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}
	if _, err := manager.store.GetQuarantined(context.Background(), provider.Name(), "workspace-1", "task-1"); !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("provisioning quarantine error = %v, want cleared tombstone", err)
	}
	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}); err != nil {
		t.Fatalf("execution after successful compensation error = %v", err)
	}
}

func TestManagerReconcilesLostCreateResponseBeforeReplacement(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.createErr = errors.New("create response lost")
	provider.createReturnsNil = true
	provider.createAllocatedOnError = true
	provider.deleteErr = errors.New("provider cleanup unavailable")
	provider.mu.Unlock()
	request := sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}

	if _, err := manager.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrProvisioningUnresolved) {
		t.Fatalf("first ExecuteSandbox() error = %v, want ErrProvisioningUnresolved", err)
	}
	intent, err := manager.store.getProvisioning(context.Background(), provider.Name(), "workspace-1", "task-1")
	if err != nil || intent.ProvisioningID == "" {
		t.Fatalf("durable provisioning intent = %+v, %v", intent, err)
	}

	provider.mu.Lock()
	provider.deleteErr = errors.New("provider cleanup still unavailable")
	provider.mu.Unlock()
	if _, err := manager.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrProvisioningUnresolved) {
		t.Fatalf("second ExecuteSandbox() error = %v, want ErrProvisioningUnresolved", err)
	}
	provider.mu.Lock()
	if provider.creates != 1 {
		t.Fatalf("creates = %d, replacement was allocated beside unresolved sandbox", provider.creates)
	}
	provider.mu.Unlock()

	if _, err := manager.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrProvisioningUnresolved) {
		t.Fatalf("cleaned inventory pass error = %v, want ErrProvisioningUnresolved", err)
	}
	provider.mu.Lock()
	if provider.creates != 1 || provider.deletes != 3 {
		provider.mu.Unlock()
		t.Fatalf("creates=%d deletes=%d, replacement started before visibility window closed", provider.creates, provider.deletes)
	}
	provider.mu.Unlock()
	storedIntent, err := manager.store.getProvisioning(context.Background(), provider.Name(), "workspace-1", "task-1")
	if err != nil || storedIntent.ProvisioningID != intent.ProvisioningID {
		t.Fatalf("intent after successful delete = %+v, %v", storedIntent, err)
	}
	now := time.Now().UTC()
	storedIntent.StartedAt = now.Add(-2 * time.Second)
	storedIntent.ExpiresAt = now.Add(-time.Second)
	encodedIntent, err := json.Marshal(storedIntent)
	if err != nil {
		t.Fatal(err)
	}
	if err := manager.store.client.Set(
		context.Background(),
		manager.store.provisioningKey(provider.Name(), "workspace-1", "task-1"),
		encodedIntent,
		manager.store.ttl,
	).Err(); err != nil {
		t.Fatal(err)
	}

	if _, err := manager.ExecuteSandbox(context.Background(), request); err != nil {
		t.Fatalf("execution after expired clean inventory pass = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 || provider.deletes != 3 {
		t.Fatalf("creates=%d deletes=%d, want orphan removed before one replacement", provider.creates, provider.deletes)
	}
}

func TestManagerFencesAmbiguousCreateWithoutInventoryMatchUntilLeaseExpiry(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.mu.Lock()
	provider.createErr = errors.New("create response lost")
	provider.createReturnsNil = true
	provider.mu.Unlock()
	request := sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}

	if _, err := manager.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrProvisioningUnresolved) {
		t.Fatalf("first ExecuteSandbox() error = %v, want ErrProvisioningUnresolved", err)
	}
	if _, err := manager.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrProvisioningUnresolved) {
		t.Fatalf("second ExecuteSandbox() error = %v, want ErrProvisioningUnresolved", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 1 {
		t.Fatalf("creates = %d, empty eventually-consistent inventory incorrectly authorized a replacement", provider.creates)
	}
}

func TestManagerRecordsQuarantineWhenCreateContextIsCancelled(t *testing.T) {
	manager, provider := newTestManager(t)
	createEntered := make(chan struct{}, 1)
	provider.mu.Lock()
	provider.createErr = errors.New("post-create validation interrupted")
	provider.createWaitsForCancel = true
	provider.createEntered = createEntered
	provider.deleteErr = errors.New("provider cleanup unavailable")
	provider.mu.Unlock()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	result := make(chan error, 1)
	go func() {
		_, err := manager.ExecuteSandbox(ctx, sandboxcontract.ExecuteRequest{
			WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
		})
		result <- err
	}()
	select {
	case <-createEntered:
		cancel()
	case <-time.After(time.Second):
		t.Fatal("provider Create was not entered")
	}
	var err error
	select {
	case err = <-result:
	case <-time.After(time.Second):
		t.Fatal("ExecuteSandbox did not return after cancellation")
	}
	if err == nil || !strings.Contains(err.Error(), "post-create validation interrupted") {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}
	quarantined, quarantineErr := manager.store.GetQuarantined(
		context.Background(), provider.Name(), "workspace-1", "task-1",
	)
	if quarantineErr != nil || quarantined.ID != "sandbox-1" {
		t.Fatalf("quarantine after cancelled create = %+v, %v", quarantined, quarantineErr)
	}
	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}); !errors.Is(err, ErrSessionQuarantined) {
		t.Fatalf("replacement demand error = %v, want ErrSessionQuarantined", err)
	}
}

func (p *fakeExternalProvider) List(_ context.Context, workspaceID string) ([]SandboxStatus, error) {
	return []SandboxStatus{{
		ID:          "sandbox-live",
		Provider:    p.Name(),
		WorkspaceID: workspaceID,
		State:       "running",
	}}, nil
}

type slowReadCloser struct {
	content []byte
	delay   time.Duration
	offset  int
}

func (r *slowReadCloser) Read(buffer []byte) (int, error) {
	if r.offset >= len(r.content) {
		return 0, io.EOF
	}
	time.Sleep(r.delay)
	buffer[0] = r.content[r.offset]
	r.offset++
	return 1, nil
}

func (*slowReadCloser) Close() error { return nil }

func TestManagerPinsFilesAndExecutionsToOneProviderSession(t *testing.T) {
	manager, provider := newTestManager(t)
	ctx := context.Background()

	_, err := manager.SandboxFilePut(ctx, sandboxcontract.FilePutRequest{
		WorkspaceID:   "workspace-1",
		TaskID:        "task-1",
		Path:          "inputs/data.txt",
		ContentBase64: "aGVsbG8=",
	})
	if err != nil {
		t.Fatalf("SandboxFilePut() error = %v", err)
	}
	_, err = manager.ExecuteSandbox(ctx, sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		CommandBody: "cat inputs/data.txt",
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
	manager, provider := newTestManager(t)
	inventory := &managerWithInventory{Manager: manager, lister: provider}
	items, err := inventory.ListSandboxes(context.Background(), "workspace-1")
	if err != nil {
		t.Fatalf("ListSandboxes() error = %v", err)
	}
	if len(items) != 1 || items[0].WorkspaceID != "workspace-1" || items[0].State != "running" {
		t.Fatalf("ListSandboxes() = %+v", items)
	}
}

func TestManagerRequiresNewDemandWhenPinnedProviderReportsExpired(t *testing.T) {
	manager, provider := newTestManager(t)
	ctx := context.Background()
	request := sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		CommandBody: "true",
	}
	if _, err := manager.ExecuteSandbox(ctx, request); err != nil {
		t.Fatalf("first ExecuteSandbox() error = %v", err)
	}
	provider.renewErr = ErrSessionNotFound
	if _, err := manager.ExecuteSandbox(ctx, request); !errors.Is(err, ErrWorkspaceRehydration) {
		t.Fatalf("expired binding demand error = %v, want ErrWorkspaceRehydration", err)
	}
	provider.mu.Lock()
	if provider.creates != 1 || len(provider.executeIDs) != 1 {
		provider.mu.Unlock()
		t.Fatalf("same demand created or executed a replacement: creates=%d executions=%v", provider.creates, provider.executeIDs)
	}
	provider.mu.Unlock()
	if _, err := manager.ExecuteSandbox(ctx, request); err != nil {
		t.Fatalf("next demand ExecuteSandbox() error = %v", err)
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

func TestManagerInvalidatesMissingSessionWithoutRetryingCommand(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.executeErr = ErrSessionNotFound
	request := sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}
	if _, err := manager.ExecuteSandbox(context.Background(), request); !errors.Is(err, ErrWorkspaceRehydration) {
		t.Fatalf("ExecuteSandbox() error = %v, want ErrWorkspaceRehydration", err)
	}
	provider.mu.Lock()
	if provider.creates != 1 || len(provider.executeIDs) != 1 {
		t.Fatalf("first demand creates=%d executions=%v, want no internal retry", provider.creates, provider.executeIDs)
	}
	provider.mu.Unlock()
	if _, err := manager.ExecuteSandbox(context.Background(), request); err != nil {
		t.Fatalf("next demand ExecuteSandbox() error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 || len(provider.executeIDs) != 2 {
		t.Fatalf("next demand creates=%d executions=%v", provider.creates, provider.executeIDs)
	}
	if got := provider.executeIDs[1]; got != "sandbox-2" {
		t.Fatalf("last execution session = %s, want sandbox-2", got)
	}
}

func TestManagerInvalidatesMissingSessionWithoutRetryingFilePut(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.putErr = ErrSessionNotFound
	request := sandboxcontract.FilePutRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "input.txt", ContentBase64: "aGVsbG8=",
	}
	if _, err := manager.SandboxFilePut(context.Background(), request); !errors.Is(err, ErrWorkspaceRehydration) {
		t.Fatalf("SandboxFilePut() error = %v, want ErrWorkspaceRehydration", err)
	}
	provider.mu.Lock()
	if provider.creates != 1 || len(provider.files) != 0 {
		t.Fatalf("first demand creates=%d files=%v, want no internal retry", provider.creates, provider.files)
	}
	provider.mu.Unlock()
	if _, err := manager.SandboxFilePut(context.Background(), request); err != nil {
		t.Fatalf("next demand SandboxFilePut() error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 {
		t.Fatalf("creates = %d, want replacement on next demand", provider.creates)
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
	if _, err := manager.ExecuteSandbox(ctx, sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "true",
	}); err != nil {
		t.Fatal(err)
	}
	if err := manager.RetireSandboxTask(ctx, "workspace-other", "task-1", 0); err != nil {
		t.Fatalf("cross-workspace idempotent retire leaked session existence: %v", err)
	}
	provider.mu.Lock()
	deletesAfterCrossWorkspaceRetire := provider.deletes
	provider.mu.Unlock()
	if deletesAfterCrossWorkspaceRetire != 0 {
		t.Fatal("cross-workspace retire deleted another workspace's sandbox")
	}
	if err := manager.RetireSandboxTask(ctx, "workspace-1", "task-1", time.Minute); err != nil {
		t.Fatalf("RetireSandboxTask(idle) error = %v", err)
	}
	if err := manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0); err != nil {
		t.Fatalf("RetireSandboxTask(force) error = %v", err)
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.deletes != 1 {
		t.Fatalf("deletes = %d, want 1", provider.deletes)
	}
}

func TestManagerScopesProviderSessionsByWorkspaceAndTask(t *testing.T) {
	manager, provider := newTestManager(t)
	ctx := context.Background()
	for _, workspaceID := range []string{"workspace-1", "workspace-2"} {
		if _, err := manager.ExecuteSandbox(ctx, sandboxcontract.ExecuteRequest{
			WorkspaceID: workspaceID, TaskID: "shared-task-id", CommandBody: "true",
		}); err != nil {
			t.Fatalf("ExecuteSandbox(%s) error = %v", workspaceID, err)
		}
	}
	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.creates != 2 {
		t.Fatalf("provider creates = %d, want independent sessions for both workspaces", provider.creates)
	}
	if len(provider.executeIDs) != 2 || provider.executeIDs[0] == provider.executeIDs[1] {
		t.Fatalf("provider execution sessions = %#v, want distinct bindings", provider.executeIDs)
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
	manager, err := NewManager(provider, store, 30*time.Millisecond, time.Minute, testManifest(), testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}

	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "sleep",
	}); err != nil {
		t.Fatalf("ExecuteSandbox() error = %v", err)
	}

	provider.mu.Lock()
	defer provider.mu.Unlock()
	if provider.renews < 2 {
		t.Fatalf("renews = %d, want heartbeat plus completion renewal", provider.renews)
	}
}

func TestManagerMovesSuccessfulExecutionFromActiveToIdleLease(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:idle-lease", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	const activeTTL = 30 * time.Millisecond
	const idleTTL = 2 * time.Minute
	provider := &fakeExternalProvider{executeDelay: 80 * time.Millisecond}
	manager, err := NewManager(provider, store, activeTTL, idleTTL, testManifest(), testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "sleep",
	}); err != nil {
		t.Fatal(err)
	}
	provider.mu.Lock()
	renewals := append([]time.Duration(nil), provider.renewTTLs...)
	provider.mu.Unlock()
	if len(renewals) < 2 || renewals[len(renewals)-1] != idleTTL {
		t.Fatalf("lease renewals = %v, want final idle TTL %s", renewals, idleTTL)
	}
	if !slices.Contains(renewals[:len(renewals)-1], activeTTL) {
		t.Fatalf("lease renewals = %v, want active heartbeat TTL %s", renewals, activeTTL)
	}
	session, err := store.Get(context.Background(), provider.Name(), "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	remaining := time.Until(session.ExpiresAt)
	if remaining <= idleTTL-time.Second || remaining > idleTTL {
		t.Fatalf("stored idle lease remaining = %s, want approximately %s", remaining, idleTTL)
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
	manager, err := NewManager(provider, store, 30*time.Millisecond, time.Minute, testManifest(), testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}

	_, err = manager.ExecuteSandbox(context.Background(), sandboxcontract.ExecuteRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1", CommandBody: "sleep",
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
	stored, err := store.Get(context.Background(), "fake", "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if stored.ID != "new" {
		t.Fatalf("stored session = %q, want replacement", stored.ID)
	}
}

func TestSessionStoreRejectsSessionCommitAfterCreationLockLoss(t *testing.T) {
	redisServer := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: redisServer.Addr()})
	store, err := NewSessionStore(client, "test:fenced-commit", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	lock := taskLock{key: "test:fenced-commit:lock", token: "owner-1"}
	if err := client.Set(ctx, lock.key, lock.token, time.Minute).Err(); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	intent := ProvisioningIntent{
		Provider: "fake", ProvisioningID: "provision-1", WorkspaceID: "workspace-1", TaskID: "task-1", StartedAt: now, ExpiresAt: now.Add(time.Minute),
	}
	if err := store.beginProvisioningIfLockOwned(ctx, intent, lock); err != nil {
		t.Fatalf("record provisioning intent: %v", err)
	}
	if err := client.Set(ctx, lock.key, "owner-2", time.Minute).Err(); err != nil {
		t.Fatal(err)
	}
	stale := &Session{ID: "session-stale", Provider: "fake", WorkspaceID: "workspace-1", TaskID: "task-1"}
	if err := store.putProvisioningIfLockOwned(ctx, stale, intent, lock); err == nil {
		t.Fatal("stale lock owner unexpectedly committed a replacement session")
	}
	if _, err := store.Get(ctx, "fake", "workspace-1", "task-1"); !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("stale lock committed a session: %v", err)
	}
	if storedIntent, err := store.getProvisioning(ctx, "fake", "workspace-1", "task-1"); err != nil || storedIntent.ProvisioningID != intent.ProvisioningID {
		t.Fatalf("provisioning intent = %+v, %v", storedIntent, err)
	}
}

func TestSessionStoreLockRenewalLossCancelsProtectedContext(t *testing.T) {
	redisServer := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: redisServer.Addr()})
	store, err := NewSessionStore(client, "test:lock-cancel", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	key := "test:lock-cancel:lock"
	if err := client.Set(ctx, key, "replacement-owner", time.Minute).Err(); err != nil {
		t.Fatal(err)
	}
	go store.renewLock(ctx, cancel, key, "stale-owner", 30*time.Millisecond, done)

	select {
	case <-ctx.Done():
	case <-time.After(time.Second):
		t.Fatal("lock loss did not cancel protected context")
	}
	if err := <-done; err == nil || !strings.Contains(err.Error(), "ownership was lost") {
		t.Fatalf("renewLock() error = %v, want ownership loss", err)
	}
}

func TestWorkspaceHydrationIsSerializedAcrossManagerReplicas(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:hydration", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	provider := &fakeExternalProvider{}
	manifest := testManifest()
	first, err := NewManager(provider, store, time.Minute, time.Minute, manifest, testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}
	second, err := NewManager(provider, store, time.Minute, time.Minute, manifest, testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var mu sync.Mutex
	hydrationCalls := 0
	entered := make(chan struct{})
	release := make(chan struct{})
	hydrate := func(context.Context) error {
		mu.Lock()
		hydrationCalls++
		if hydrationCalls == 1 {
			close(entered)
		}
		mu.Unlock()
		<-release
		return nil
	}
	errorsByReplica := make(chan error, 2)
	go func() {
		errorsByReplica <- first.EnsureWorkspaceHydrated(ctx, "workspace-1", "task-1", strings.Repeat("a", 64), hydrate)
	}()
	<-entered
	go func() {
		errorsByReplica <- second.EnsureWorkspaceHydrated(ctx, "workspace-1", "task-1", strings.Repeat("a", 64), hydrate)
	}()
	time.Sleep(100 * time.Millisecond)
	mu.Lock()
	gotWhileLocked := hydrationCalls
	mu.Unlock()
	if gotWhileLocked != 1 {
		t.Fatalf("hydration calls while distributed lock held = %d, want 1", gotWhileLocked)
	}
	close(release)
	for range 2 {
		if err := <-errorsByReplica; err != nil {
			t.Fatal(err)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if hydrationCalls != 1 {
		t.Fatalf("hydration calls = %d, want 1", hydrationCalls)
	}
}

// The stream a download returns outlives the call that opened it. A provider
// serves the file as the body of that request, and the artifact publisher reads
// it afterwards, so cancelling the open context on return made every delivered
// file unreadable -- the task's own output came back as "context canceled".
func TestStreamedDownloadOutlivesTheCallThatOpenedIt(t *testing.T) {
	manager, provider := newTestManager(t)
	content := []byte("delivered")
	digest := sha256.Sum256(content)
	if _, err := manager.SandboxFileUpload(context.Background(), FileUpload{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "report.txt", Size: int64(len(content)), SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, bytes.NewReader(content)); err != nil {
		t.Fatal(err)
	}
	provider.mu.Lock()
	provider.streamBoundToOpenContext = true
	provider.mu.Unlock()

	download, err := manager.SandboxFileDownload(context.Background(), "workspace-1", "task-1", "report.txt")
	if err != nil {
		t.Fatalf("SandboxFileDownload() error = %v", err)
	}
	read, err := io.ReadAll(download.Content)
	if closeErr := download.Content.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		t.Fatalf("reading the delivered file after the open call returned: %v", err)
	}
	if !bytes.Equal(read, content) {
		t.Fatalf("download = %q, want %q", read, content)
	}
}

func TestStreamedDownloadRenewsProviderLeaseUntilReaderCloses(t *testing.T) {
	server := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: server.Addr()})
	t.Cleanup(func() { _ = client.Close() })
	store, err := NewSessionStore(client, "test:download-heartbeat", time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	provider := &fakeExternalProvider{}
	manager, err := NewManager(provider, store, 30*time.Millisecond, time.Minute, testManifest(), testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}
	content := []byte("streamed")
	digest := sha256.Sum256(content)
	if _, err := manager.SandboxFileUpload(context.Background(), FileUpload{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Path: "result.txt", Size: int64(len(content)), SHA256: hex.EncodeToString(digest[:]), Mode: 0o600,
	}, bytes.NewReader(content)); err != nil {
		t.Fatal(err)
	}
	provider.mu.Lock()
	provider.renews = 0
	provider.readDelay = 15 * time.Millisecond
	provider.mu.Unlock()
	download, err := manager.SandboxFileDownload(context.Background(), "workspace-1", "task-1", "result.txt")
	if err != nil {
		t.Fatal(err)
	}
	read, err := io.ReadAll(download.Content)
	if closeErr := download.Content.Close(); err == nil {
		err = closeErr
	}
	if err != nil || !bytes.Equal(read, content) {
		t.Fatalf("download = %q, error = %v", read, err)
	}
	provider.mu.Lock()
	renewewals := provider.renews
	provider.mu.Unlock()
	if renewewals < 2 {
		t.Fatalf("provider renewals during slow stream = %d, want at least 2", renewewals)
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
	manager, err := NewManager(provider, store, 15*time.Minute, time.Minute, testManifest(), testWorkspaceLimits())
	if err != nil {
		t.Fatal(err)
	}
	return manager, provider
}

func testManifest() *runtimeinfo.Manifest {
	return &runtimeinfo.Manifest{
		SchemaVersion:      2,
		ImageVersion:       "runtime-test",
		Python:             runtimeinfo.PythonRuntime{Version: "3.12", Executable: "/usr/bin/python3"},
		Node:               runtimeinfo.NodeRuntime{Version: "v22"},
		Tools:              map[string]string{},
		Packages:           map[string]string{},
		ManagedEnvironment: "mutable",
		Features: runtimeinfo.Features{
			Browser:                    "none",
			ManagedEnvironmentMutation: true,
			ArbitraryWorkspaceCode:     true,
		},
		ExecutionSupervisor: testSupervisorAttestation(),
	}
}
