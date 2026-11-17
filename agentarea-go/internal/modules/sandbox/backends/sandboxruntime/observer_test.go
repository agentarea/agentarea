package sandboxruntime

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"
)

type lifecycleObserverStub struct {
	mu           sync.Mutex
	allocations  []SessionSnapshot
	leases       []string
	missing      int
	provisioning []ProvisioningObservation
	deletes      []DeleteResult
	failAll      bool
	beforeErr    error
	mutate       bool
}

func (o *lifecycleObserverStub) fail() error {
	if o.failAll {
		return errors.New("observation unavailable")
	}
	return nil
}

func (o *lifecycleObserverStub) Allocation(_ context.Context, session SessionSnapshot) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	if o.mutate {
		session.Resources["cpu"] = "999"
	}
	o.allocations = append(o.allocations, session)
	return o.fail()
}

func (o *lifecycleObserverStub) LeaseRenewed(_ context.Context, _ SessionSnapshot, state string, _ time.Time) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.leases = append(o.leases, state)
	return o.fail()
}

func (o *lifecycleObserverStub) Missing(context.Context, SessionSnapshot) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.missing++
	return o.fail()
}

func (o *lifecycleObserverStub) Provisioning(_ context.Context, observation ProvisioningObservation) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.provisioning = append(o.provisioning, observation)
	return o.fail()
}

func (o *lifecycleObserverStub) BeforeDelete(context.Context, DeleteAttempt) error {
	return o.beforeErr
}

func (o *lifecycleObserverStub) AfterDelete(ctx context.Context, result DeleteResult) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	o.deletes = append(o.deletes, result)
	return nil
}

func TestObserverSeesEachProviderSessionAsItsOwnAllocation(t *testing.T) {
	manager, _ := newTestManager(t)
	observer := &lifecycleObserverStub{}
	manager.SetLifecycleObserver(observer)
	ctx := context.Background()
	first, err := manager.ensure(ctx, "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := manager.ensure(ctx, "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}
	if err := manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0); err != nil {
		t.Fatal(err)
	}
	second, err := manager.ensure(ctx, "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	sessions := map[string]bool{}
	for _, allocation := range observer.allocations {
		if allocation.WorkspaceID != "workspace-1" || allocation.TaskID != "task-1" || allocation.CreatedAt.IsZero() {
			t.Fatalf("snapshot lost binding identity: %+v", allocation)
		}
		sessions[allocation.ID] = true
	}
	if len(sessions) != 2 || !sessions[first.ID] || !sessions[second.ID] {
		t.Fatalf("allocation sessions = %v", sessions)
	}
	if len(observer.deletes) != 1 || observer.deletes[0].Outcome != DeleteAccepted || observer.deletes[0].Attempt.Reason != "retirement" {
		t.Fatalf("retirement outcome = %+v", observer.deletes)
	}
}

func TestObserverFailedProviderDeleteIsNotReportedAccepted(t *testing.T) {
	manager, provider := newTestManager(t)
	observer := &lifecycleObserverStub{}
	manager.SetLifecycleObserver(observer)
	ctx := context.Background()
	if _, err := manager.ensure(ctx, "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}
	provider.deleteErr = errors.New("provider unavailable")
	if err := manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0); err == nil {
		t.Fatal("expected delete failure")
	}
	if len(observer.deletes) != 1 || observer.deletes[0].Outcome != DeleteFailed {
		t.Fatalf("failed delete outcome = %+v", observer.deletes)
	}
	if _, err := manager.store.Get(ctx, "fake", "workspace-1", "task-1"); err != nil {
		t.Fatalf("lost failed-delete binding: %v", err)
	}
}

func TestObserverFailureBeforeDeleteStillDeletesExactlyOnce(t *testing.T) {
	manager, provider := newTestManager(t)
	observer := &lifecycleObserverStub{}
	manager.SetLifecycleObserver(observer)
	ctx := context.Background()
	session, err := manager.ensure(ctx, "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	observer.beforeErr = errors.New("ledger unavailable")
	provider.deleteErr = ErrSessionNotFound
	err = manager.deleteSession(ctx, session, "retirement")
	if !errors.Is(err, ErrLifecycleObservation) {
		t.Fatalf("observation failure was not marked: %v", err)
	}
	if sessionAlreadyGone(err) {
		t.Fatal("an observation failure was normalized away with NotFound")
	}
	if provider.deletes != 1 {
		t.Fatalf("provider deletes = %d, want exactly 1", provider.deletes)
	}
	if len(observer.deletes) != 1 || observer.deletes[0].Outcome != DeleteMissing {
		t.Fatalf("after-delete outcome = %+v", observer.deletes)
	}
}

func TestObserverCannotChangeTheSession(t *testing.T) {
	manager, _ := newTestManager(t)
	observer := &lifecycleObserverStub{mutate: true}
	manager.SetLifecycleObserver(observer)
	session, err := manager.ensure(context.Background(), "workspace-1", "task-1")
	if err != nil {
		t.Fatal(err)
	}
	session.Data = map[string]string{"cpu": "2"}
	if err := manager.observeAllocation(context.Background(), session); err != nil {
		t.Fatal(err)
	}
	if session.Data["cpu"] != "2" {
		t.Fatalf("observer changed the session: %v", session.Data)
	}
}

func TestObserverFailureSurfacesFromDemandAdmission(t *testing.T) {
	manager, _ := newTestManager(t)
	manager.SetLifecycleObserver(&lifecycleObserverStub{failAll: true})
	if _, err := manager.ensure(context.Background(), "workspace-1", "task-1"); !errors.Is(err, ErrLifecycleObservation) {
		t.Fatalf("observation failure was hidden: %v", err)
	}
}

func TestObserverOpaqueProvisioningFailureIsNotAnAllocation(t *testing.T) {
	manager, provider := newTestManager(t)
	provider.createErr = errors.New("opaque SDK initialization failure")
	provider.createReturnsNil = true
	observer := &lifecycleObserverStub{}
	manager.SetLifecycleObserver(observer)
	if _, err := manager.ensure(context.Background(), "workspace-1", "task-1"); err == nil {
		t.Fatal("opaque provisioning failure was hidden")
	}
	if len(observer.allocations) != 0 {
		t.Fatalf("invented allocation for an opaque provider response: %+v", observer.allocations)
	}
	if len(observer.provisioning) != 2 || observer.provisioning[0].Phase != ProvisioningStarted || observer.provisioning[1].Phase != ProvisioningFailed {
		t.Fatalf("provisioning observations = %+v", observer.provisioning)
	}
	started, failed := observer.provisioning[0], observer.provisioning[1]
	if started.Intent.ProvisioningID != failed.Intent.ProvisioningID || !started.RespondedAt.IsZero() || failed.RespondedAt.Before(failed.RequestedAt) {
		t.Fatalf("provisioning phases are not one bounded attempt: %+v", observer.provisioning)
	}
}

func TestFailedE2BBootstrapKeepsTheEarlierAllocationObservation(t *testing.T) {
	enteredBootstrap := make(chan time.Time, 1)
	releaseBootstrap := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/sandboxes":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"sandboxID":"allocated-before-bootstrap","envdVersion":"0.1.0"}`))
		case "/filesystem.Filesystem/MakeDir":
			enteredBootstrap <- time.Now().UTC()
			select {
			case <-releaseBootstrap:
				http.Error(w, "bootstrap failed", http.StatusBadRequest)
			case <-r.Context().Done():
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	provider, err := NewE2BProvider(testE2BConfig("e2b", server.URL))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	type createResult struct {
		session *Session
		err     error
	}
	result := make(chan createResult, 1)
	go func() {
		session, err := provider.Create(ctx, CreateRequest{
			WorkspaceID: "workspace-1", TaskID: "task-1", ProvisioningID: "provision-1",
		})
		result <- createResult{session: session, err: err}
	}()
	var bootstrapAt time.Time
	select {
	case bootstrapAt = <-enteredBootstrap:
	case <-ctx.Done():
		t.Fatal("bootstrap was not reached")
	}
	close(releaseBootstrap)
	created := <-result
	if created.err == nil || created.session == nil {
		t.Fatalf("failed initialization lost allocation: %+v", created)
	}
	if created.session.CreatedAt.IsZero() || created.session.CreatedAt.After(bootstrapAt) {
		t.Fatalf("allocation timestamp %s did not precede initialization at %s", created.session.CreatedAt, bootstrapAt)
	}
	manager, _ := newTestManager(t)
	manager.provider = provider
	createdAt := created.session.CreatedAt
	manager.bindSessionIdentity(created.session, "workspace-1", "task-1")
	snapshot := sessionSnapshot(created.session)
	if snapshot.CreatedAtSource != "provider_create_response_observed" || !snapshot.CreatedAt.Equal(createdAt) {
		t.Fatalf("allocation provenance changed during manager binding: %+v", snapshot)
	}
}
