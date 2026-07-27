package mcpidle

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/backends"
)

// The selection predicate (only lazy instances, only running, NULL
// last_used_at is NOT idle) lives in SQL and is not covered here: this
// repository has no database-backed Go tests, and adding a harness for one
// query would introduce a pattern rather than verify Postgres semantics.
// Verify it against a real database — see the PR's manual check.
//
// What is covered is everything downstream of the query: how an instance is
// addressed when stopping it, and the guards that decide whether the loop runs
// at all.

type fakeBackend struct {
	backends.Backend
	deleted []string
	err     error
}

func (f *fakeBackend) DeleteInstance(_ context.Context, instanceID string) error {
	f.deleted = append(f.deleted, instanceID)
	return f.err
}

func newTestReaper(backend backends.Backend) *Reaper {
	return New(backend, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

// recordingRelease stands in for the UPDATE that marks an instance
// unprovisioned, capturing the ids it was asked to release.
type recordingRelease struct {
	released []string
	err      error
}

func (r *recordingRelease) fn(_ context.Context, id string) error {
	r.released = append(r.released, id)
	return r.err
}

// Instances are keyed by id everywhere the backends can be asked about them:
// the docker backend sets the service name to the instance id and stamps
// MCP_INSTANCE_ID into the container env, and the Kubernetes backend records it
// in the agentarea.io/instance-id annotation and the configmap. The display
// name resolves on neither, so passing it would make the sweep a silent no-op
// that only logs "not found".
func TestStopAddressesInstancesByIDNotName(t *testing.T) {
	backend := &fakeBackend{}
	reaper := newTestReaper(backend)
	release := &recordingRelease{}

	idle := []idleInstance{
		{id: "9f1c1a3e-0000-4000-8000-000000000001", name: "github-mcp"},
		{id: "9f1c1a3e-0000-4000-8000-000000000002", name: "slack-mcp"},
	}

	stopped := reaper.stop(context.Background(), idle, time.Minute, release.fn)

	if stopped != len(idle) {
		t.Fatalf("expected %d stopped, got %d", len(idle), stopped)
	}
	for i, want := range []string{idle[0].id, idle[1].id} {
		if backend.deleted[i] != want {
			t.Errorf("instance %d was addressed as %q; the backends only resolve the id %q",
				i, backend.deleted[i], want)
		}
	}
}

// Stopping the workload without releasing the instance's state leaves the row
// claiming it is provisioned, and the next tool call dispatches into nothing
// instead of provisioning it again — which is the whole point of reaping a lazy
// instance.
func TestStopReleasesInstanceStateAfterDeleting(t *testing.T) {
	backend := &fakeBackend{}
	reaper := newTestReaper(backend)
	release := &recordingRelease{}

	idle := []idleInstance{{id: "9f1c1a3e-0000-4000-8000-000000000001", name: "github-mcp"}}
	reaper.stop(context.Background(), idle, time.Minute, release.fn)

	if len(release.released) != 1 || release.released[0] != idle[0].id {
		t.Errorf("expected the stopped instance to be released, got %v", release.released)
	}
}

// A workload that could not be stopped must keep its state, or the row would
// claim "gone" while the workload is still running.
func TestStopDoesNotReleaseWhenDeleteFails(t *testing.T) {
	backend := &fakeBackend{err: errors.New("boom")}
	reaper := newTestReaper(backend)
	release := &recordingRelease{}

	idle := []idleInstance{{id: "a", name: "one"}}
	reaper.stop(context.Background(), idle, time.Minute, release.fn)

	if len(release.released) != 0 {
		t.Errorf("state was released for an instance that is still running: %v", release.released)
	}
}

// A stop whose state write failed is not a clean reclamation: the workload is
// gone but the row still points at it, so counting it would hide the breakage.
func TestStopDoesNotCountAFailedRelease(t *testing.T) {
	backend := &fakeBackend{}
	reaper := newTestReaper(backend)
	release := &recordingRelease{err: errors.New("db down")}

	idle := []idleInstance{{id: "a", name: "one"}}
	stopped := reaper.stop(context.Background(), idle, time.Minute, release.fn)

	if stopped != 0 {
		t.Errorf("expected 0 counted when the release failed, got %d", stopped)
	}
}

// One instance that cannot be stopped must not keep every other one running.
func TestStopContinuesPastAFailure(t *testing.T) {
	backend := &fakeBackend{err: errors.New("instance not found")}
	reaper := newTestReaper(backend)
	release := &recordingRelease{}

	idle := []idleInstance{{id: "a", name: "one"}, {id: "b", name: "two"}}
	stopped := reaper.stop(context.Background(), idle, time.Minute, release.fn)

	if stopped != 0 {
		t.Errorf("a failed delete must not count as stopped, got %d", stopped)
	}
	if len(backend.deleted) != 2 {
		t.Errorf("the sweep stopped early: attempted %d of %d", len(backend.deleted), len(idle))
	}
}

func TestReapDisabledWithoutTimeout(t *testing.T) {
	backend := &fakeBackend{}
	reaper := newTestReaper(backend)

	// A nil handle proves the disabled path returns before touching the
	// database: reaping must be opt-in, not "on with a zero window".
	stopped, err := reaper.Reap(context.Background(), nil, 0)
	if err != nil {
		t.Fatalf("expected no error when disabled, got %v", err)
	}
	if stopped != 0 {
		t.Errorf("expected nothing stopped when disabled, got %d", stopped)
	}
}

func TestReapRejectsNegativeTimeout(t *testing.T) {
	reaper := newTestReaper(&fakeBackend{})

	stopped, err := reaper.Reap(context.Background(), nil, -1*time.Minute)
	if err != nil || stopped != 0 {
		t.Errorf("a negative window must disable reaping, got stopped=%d err=%v", stopped, err)
	}
}

func TestStartReturnsImmediatelyWhenDisabled(t *testing.T) {
	reaper := newTestReaper(&fakeBackend{})

	done := make(chan struct{})
	go func() {
		defer close(done)
		reaper.Start(context.Background(), nil, 0, time.Second)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Start blocked with reaping disabled; it must not hold a goroutine")
	}
}

// A non-positive interval would panic time.NewTicker, taking the manager down
// on nothing worse than a misconfigured duration.
func TestStartRefusesNonPositiveInterval(t *testing.T) {
	reaper := newTestReaper(&fakeBackend{})

	done := make(chan struct{})
	go func() {
		defer close(done)
		reaper.Start(context.Background(), nil, time.Hour, 0)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Start did not reject a zero sweep interval")
	}
}

func TestStartStopsOnContextCancel(t *testing.T) {
	reaper := newTestReaper(&fakeBackend{})
	ctx, cancel := context.WithCancel(context.Background())

	done := make(chan struct{})
	go func() {
		defer close(done)
		// A long interval means the loop is parked on the ticker, so returning
		// proves cancellation wins rather than a tick happening to fire.
		reaper.Start(ctx, nil, time.Hour, time.Hour)
	}()

	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Start ignored context cancellation")
	}
}
