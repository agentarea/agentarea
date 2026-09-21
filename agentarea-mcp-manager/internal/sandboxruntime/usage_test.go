package sandboxruntime

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/agentarea/mcp-manager/internal/usage"
)

type lifecycleRecorder struct {
	events   map[string]usage.Event
	attempts []usage.Event
	fail     bool
}

func (r *lifecycleRecorder) Record(_ context.Context, event usage.Event) error {
	r.attempts = append(r.attempts, event)
	if r.fail {
		return errors.New("usage unavailable")
	}
	if r.events == nil {
		r.events = make(map[string]usage.Event)
	}
	if previous, ok := r.events[event.ID]; ok && !reflect.DeepEqual(previous, event) {
		return errors.New("event identity collision")
	}
	r.events[event.ID] = event
	return nil
}

func TestUsageAllocationSurvivesReuseAndReplacement(t *testing.T) {
	manager, _ := newTestManager(t)
	recorder := &lifecycleRecorder{}
	manager.SetUsageRecorder(recorder)
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
	allocations := make(map[string]bool)
	for _, event := range recorder.events {
		if event.Kind == "sandbox.allocated" {
			allocations[event.IncarnationID] = true
		}
	}
	if len(allocations) != 2 || !allocations[first.ID] || !allocations[second.ID] {
		t.Fatalf("allocation identities = %v", allocations)
	}
}

func TestUsageFailedProviderDeleteDoesNotClaimTermination(t *testing.T) {
	manager, provider := newTestManager(t)
	recorder := &lifecycleRecorder{}
	manager.SetUsageRecorder(recorder)
	ctx := context.Background()
	if _, err := manager.ensure(ctx, "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}
	provider.deleteErr = errors.New("provider unavailable")
	if err := manager.RetireSandboxTask(ctx, "workspace-1", "task-1", 0); err == nil {
		t.Fatal("expected delete failure")
	}
	failed := false
	for _, event := range recorder.events {
		if event.Kind == "sandbox.delete_accepted" || event.Kind == "sandbox.terminated" {
			t.Fatalf("unproven deletion: %s", event.Kind)
		}
		failed = failed || event.Kind == "sandbox.delete_failed"
	}
	if !failed {
		t.Fatal("missing failed deletion observation")
	}
	if _, err := manager.store.Get(ctx, "fake", "workspace-1", "task-1"); err != nil {
		t.Fatalf("lost failed-delete binding: %v", err)
	}
}

func TestUsageAllocationRecorderFailurePreservesIdentity(t *testing.T) {
	manager, _ := newTestManager(t)
	recorder := &lifecycleRecorder{fail: true}
	manager.SetUsageRecorder(recorder)
	ctx := context.Background()
	if _, err := manager.ensure(ctx, "workspace-1", "task-1"); err == nil {
		t.Fatal("usage failure was hidden")
	}
	var first usage.Event
	for _, event := range recorder.attempts {
		if event.Kind == "sandbox.allocated" {
			first = event
			break
		}
	}
	if first.ID == "" {
		t.Fatal("allocation failure was not observed")
	}
	recorder.fail = false
	if _, err := manager.ensure(ctx, "workspace-1", "task-1"); err != nil {
		t.Fatal(err)
	}
	if got := recorder.events[first.ID]; !reflect.DeepEqual(first, got) {
		t.Fatalf("allocation changed across retry: %#v -> %#v", first, got)
	}
}
