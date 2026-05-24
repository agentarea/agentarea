package sandboxcontrol

import (
	"context"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/warmpool"
)

func TestServiceCreateExecutionPublishesRequestedEvent(t *testing.T) {
	store := newMemoryStore()
	events := &recordingEventBus{}
	service := NewService(store, events)

	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkflowID: "wf-1",
		Command: warmpool.ExecuteRequest{
			ScriptName:    "cmd.sh",
			ScriptContent: "echo ok",
		},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
	if record.ID == "" {
		t.Fatal("record id is empty")
	}
	if record.Status != ExecutionStatusQueued {
		t.Fatalf("status = %q, want queued", record.Status)
	}
	if len(events.requested) != 1 || events.requested[0].ID != record.ID {
		t.Fatalf("requested events = %#v", events.requested)
	}
}

func TestServiceApplyExecutionEventUpdatesState(t *testing.T) {
	store := newMemoryStore()
	events := &recordingEventBus{}
	service := NewService(store, events)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Command: warmpool.ExecuteRequest{
			ScriptName:    "cmd.sh",
			ScriptContent: "echo ok",
		},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}

	updated, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType: EventTypeExecutionCompleted,
		OutputRefs: []SandboxObjectReference{{
			URI: "s3://bucket/path/result.txt",
		}},
	})
	if err != nil {
		t.Fatalf("ApplyExecutionEvent() error = %v", err)
	}
	if updated.Status != ExecutionStatusCompleted {
		t.Fatalf("status = %q, want completed", updated.Status)
	}
	if updated.CompletedAt == nil {
		t.Fatal("CompletedAt is nil")
	}
	if len(updated.OutputRefs) != 1 {
		t.Fatalf("output refs = %#v", updated.OutputRefs)
	}
	if len(events.lifecycle) != 1 || events.lifecycle[0] != EventTypeExecutionCompleted {
		t.Fatalf("lifecycle events = %#v", events.lifecycle)
	}
}

type memoryStore struct {
	records map[string]*ExecutionRecord
}

func newMemoryStore() *memoryStore {
	return &memoryStore{records: map[string]*ExecutionRecord{}}
}

func (s *memoryStore) CreateExecution(_ context.Context, record *ExecutionRecord) error {
	copied := *record
	s.records[record.ID] = &copied
	return nil
}

func (s *memoryStore) GetExecution(_ context.Context, id string) (*ExecutionRecord, error) {
	record, ok := s.records[id]
	if !ok {
		return nil, ErrExecutionNotFound
	}
	copied := *record
	return &copied, nil
}

func (s *memoryStore) UpdateExecution(_ context.Context, record *ExecutionRecord) error {
	record.UpdatedAt = time.Now().UTC()
	copied := *record
	s.records[record.ID] = &copied
	return nil
}

type recordingEventBus struct {
	requested []*ExecutionRecord
	lifecycle []string
}

func (b *recordingEventBus) PublishRequested(_ context.Context, record *ExecutionRecord) error {
	b.requested = append(b.requested, record)
	return nil
}

func (b *recordingEventBus) PublishLifecycleEvent(_ context.Context, _ *ExecutionRecord, eventType string) error {
	b.lifecycle = append(b.lifecycle, eventType)
	return nil
}
