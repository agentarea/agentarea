package container

import (
	"context"
	"testing"
	"time"
)

// The reaper's selection predicate (only lazy instances, only running, NULL
// last_used_at is NOT idle) lives in SQL and is not covered here: this
// repository has no database-backed Go tests, and adding a harness for one
// query would introduce a pattern rather than verify Postgres semantics.
// Verify it against a real database — see the PR's manual check.
//
// What is covered is the guard that decides whether the loop runs at all,
// because getting that wrong silently either disables reclamation or starts a
// sweep that deletes containers on a deployment that never opted in.

func TestReapIdleInstancesDisabledWithoutTimeout(t *testing.T) {
	manager := newTestManager(t)

	// A nil handle proves the disabled path returns before touching the
	// database: reaping must be opt-in, not "on with a zero window".
	stopped, err := manager.ReapIdleInstances(context.Background(), nil, 0)
	if err != nil {
		t.Fatalf("expected no error when disabled, got %v", err)
	}
	if stopped != 0 {
		t.Errorf("expected nothing stopped when disabled, got %d", stopped)
	}
}

func TestReapIdleInstancesRejectsNegativeTimeout(t *testing.T) {
	manager := newTestManager(t)

	stopped, err := manager.ReapIdleInstances(context.Background(), nil, -1*time.Minute)
	if err != nil || stopped != 0 {
		t.Errorf("a negative window must disable reaping, got stopped=%d err=%v", stopped, err)
	}
}

func TestStartIdleReaperReturnsImmediatelyWhenDisabled(t *testing.T) {
	manager := newTestManager(t)

	done := make(chan struct{})
	go func() {
		defer close(done)
		manager.StartIdleReaper(context.Background(), nil, 0, time.Second)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("StartIdleReaper blocked with reaping disabled; it must not hold a goroutine")
	}
}

func TestStartIdleReaperStopsOnContextCancel(t *testing.T) {
	manager := newTestManager(t)
	ctx, cancel := context.WithCancel(context.Background())

	done := make(chan struct{})
	go func() {
		defer close(done)
		// A long interval means the loop is parked on the ticker, so returning
		// proves cancellation wins rather than a tick happening to fire.
		manager.StartIdleReaper(ctx, nil, time.Hour, time.Hour)
	}()

	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("StartIdleReaper ignored context cancellation")
	}
}

func TestRunIdleReaperReturnsWhenTimeoutUnset(t *testing.T) {
	// The default config leaves MCPIdleTimeout at zero, so the goroutine
	// Initialize starts must exit rather than sit idle forever.
	manager := newTestManager(t)

	done := make(chan struct{})
	go func() {
		defer close(done)
		manager.runIdleReaper(context.Background())
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("runIdleReaper blocked although no idle timeout is configured")
	}
}
