package sandboxcontrol

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestServiceDerivesStatusAndRejectsBackwardTransitions(t *testing.T) {
	service := newTestService(t, newMemoryStore(), testMaxExecutionTimeoutSeconds)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Command: warmpool.ExecuteRequest{CommandBody: "true"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType: EventTypeExecutionCompleted, Status: ExecutionStatusRunning,
	}); !errors.Is(err, ErrInvalidExecution) {
		t.Fatalf("mismatched status error = %v, want ErrInvalidExecution", err)
	}
	if _, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType: EventTypeExecutionStarted,
	}); !errors.Is(err, ErrInvalidExecution) {
		t.Fatalf("queued -> running error = %v, want ErrInvalidExecution", err)
	}
}

func TestServiceTerminalReplayIsIdempotent(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceID: "workspace-1", TaskID: "task-1",
		Command: warmpool.ExecuteRequest{CommandBody: "true"},
	})
	if err != nil {
		t.Fatal(err)
	}
	moveExecutionToRunning(t, service, record.ID)
	event := ExecutionEventRequest{EventType: EventTypeExecutionCompleted, Result: &warmpool.ExecuteResponse{ExitCode: 0}}
	completed, err := service.ApplyExecutionEvent(context.Background(), record.ID, event)
	if err != nil {
		t.Fatal(err)
	}
	replayed, err := service.ApplyExecutionEvent(context.Background(), record.ID, event)
	if err != nil {
		t.Fatalf("terminal replay error = %v", err)
	}
	if replayed.Revision != completed.Revision || len(store.lifecycle) != 3 {
		t.Fatalf("terminal replay mutated aggregate/events: revision=%d events=%v", replayed.Revision, store.lifecycle)
	}
}

func TestServiceCreateExecutionPublishesRequestedEvent(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)

	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkflowID:           "wf-1",
		WorkspaceManifestRef: validTestManifestRef("workspace-1", "task-1", "a", 1, 7),
		Command: warmpool.ExecuteRequest{
			CommandBody: "echo ok",
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
	if len(store.requested) != 1 || store.requested[0].ID != record.ID {
		t.Fatalf("requested events = %#v", store.requested)
	}
}

func TestServiceCreatesSessionExecutionWithoutWorkspaceManifest(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)

	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkflowID:  "wf-1",
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		Command: warmpool.ExecuteRequest{
			CommandBody: "echo ok",
		},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
	if record.Status != ExecutionStatusQueued || record.WorkspaceManifestRef != nil {
		t.Fatalf("session record = %#v", record)
	}
	if len(store.requested) != 1 || store.requested[0].ID != record.ID {
		t.Fatalf("requested events = %#v", store.requested)
	}
}

func TestServiceRejectsSessionExecutionWithoutTaskIdentity(t *testing.T) {
	service := newTestService(t, newMemoryStore(), testMaxExecutionTimeoutSeconds)

	_, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkflowID: "wf-1",
		Command: warmpool.ExecuteRequest{
			CommandBody: "echo ok",
		},
	})

	if err == nil || !strings.Contains(err.Error(), "task_id and workspace_id are required") {
		t.Fatalf("CreateExecution() error = %v, want task identity requirement", err)
	}
}

func TestServiceRejectsExecutionTimeoutAboveConfiguredDataPlaneMaximum(t *testing.T) {
	service := newTestService(t, newMemoryStore(), 17)

	_, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		Command: warmpool.ExecuteRequest{
			CommandBody: "echo ok", TimeoutSeconds: 18,
		},
	})

	if err == nil || !strings.Contains(err.Error(), "between 1 and 17") {
		t.Fatalf("CreateExecution() error = %v, want configured data-plane maximum", err)
	}
}

func TestServiceCompletesSessionExecutionWithOutputRefs(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)
	digest := strings.Repeat("a", 64)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		Command:     warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
	moveExecutionToRunning(t, service, record.ID)
	updated, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType: EventTypeExecutionCompleted,
		OutputRefs: []SandboxObjectReference{{
			RelativePath:        ".agentarea/executions/" + record.ID + "/stdout.txt",
			ObjectURI:           "s3://bucket/workspaces/workspace-1/tasks/task-1/objects/" + digest,
			ObjectVersionOrETag: "etag",
			SHA256:              digest,
			ContentType:         "text/plain; charset=utf-8",
			Mode:                0o600,
		}},
	})
	if err != nil {
		t.Fatalf("ApplyExecutionEvent() error = %v", err)
	}
	if updated.Status != ExecutionStatusCompleted || len(updated.OutputRefs) != 1 || updated.WorkspaceManifestRef != nil {
		t.Fatalf("session completion = %#v", updated)
	}
}

func TestServiceDoesNotRequireRuntimeProfile(t *testing.T) {
	service := newTestService(t, newMemoryStore(), testMaxExecutionTimeoutSeconds)
	_, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceManifestRef: validTestManifestRef("workspace-1", "task-1", "a", 1, 7),
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
}

func validTestManifestRef(workspaceID, taskID, digestCharacter string, generation, fencingToken int64) *workspace.ManifestRef {
	digest := strings.Repeat(digestCharacter, 64)
	return &workspace.ManifestRef{
		SchemaVersion:  workspace.SchemaVersion,
		WorkspaceID:    workspaceID,
		TaskID:         taskID,
		Generation:     generation,
		ManifestURI:    "s3://bucket/workspaces/" + workspaceID + "/tasks/" + taskID + "/manifests/" + fmt.Sprint(generation) + "-" + digest + ".json",
		ManifestSHA256: digest,
		BaseGeneration: generation - 1,
		FencingToken:   fencingToken,
	}
}

func TestServiceApplyExecutionEventUpdatesState(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)
	digest := strings.Repeat("a", 64)
	baseRef := &workspace.ManifestRef{
		SchemaVersion:  workspace.SchemaVersion,
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Generation:     1,
		ManifestURI:    "s3://bucket/workspaces/workspace-1/tasks/task-1/manifests/1-" + digest + ".json",
		ManifestSHA256: digest,
		BaseGeneration: 0,
		FencingToken:   7,
	}
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceID:          "workspace-1",
		TaskID:               "task-1",
		WorkspaceManifestRef: baseRef,
		Command: warmpool.ExecuteRequest{
			CommandBody: "echo ok",
		},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
	moveExecutionToRunning(t, service, record.ID)

	nextRef := *baseRef
	nextRef.Generation = 2
	nextRef.BaseGeneration = 1
	nextRef.ManifestURI = "s3://bucket/workspaces/workspace-1/tasks/task-1/manifests/2-" + digest + ".json"
	updated, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType:            EventTypeExecutionCompleted,
		WorkspaceManifestRef: &nextRef,
		OutputRefs: []SandboxObjectReference{{
			RelativePath:        "result.txt",
			ObjectURI:           "s3://bucket/workspaces/workspace-1/tasks/task-1/objects/" + digest,
			ObjectVersionOrETag: "etag",
			SHA256:              digest,
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
	if len(store.lifecycle) != 3 || store.lifecycle[2] != EventTypeExecutionCompleted {
		t.Fatalf("lifecycle events = %#v", store.lifecycle)
	}
}

func TestServiceRejectsUntrustedCompletionRefsBeforeRedisPersistence(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)
	digest := strings.Repeat("b", 64)
	baseRef := &workspace.ManifestRef{
		SchemaVersion:  workspace.SchemaVersion,
		WorkspaceID:    "workspace-1",
		TaskID:         "task-1",
		Generation:     1,
		ManifestURI:    "s3://bucket/workspaces/workspace-1/tasks/task-1/manifests/1-" + digest + ".json",
		ManifestSHA256: digest,
		BaseGeneration: 0,
		FencingToken:   9,
	}
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceID:          baseRef.WorkspaceID,
		TaskID:               baseRef.TaskID,
		WorkspaceManifestRef: baseRef,
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
	moveExecutionToRunning(t, service, record.ID)
	malicious := *baseRef
	malicious.Generation = 2
	malicious.BaseGeneration = 1
	malicious.ManifestURI = "s3://bucket/workspaces/workspace-1/tasks/task-1/manifests/2-" + digest + ".json?X-Amz-Signature=secret"
	if _, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType:            EventTypeExecutionCompleted,
		WorkspaceManifestRef: &malicious,
	}); err == nil {
		t.Fatal("completion event with a signed URL was accepted")
	}
	stored, err := service.GetExecution(context.Background(), record.ID)
	if err != nil {
		t.Fatal(err)
	}
	if stored.Status != ExecutionStatusRunning || strings.Contains(stored.WorkspaceManifestRef.ManifestURI, "X-Amz") {
		t.Fatalf("untrusted completion mutated Redis record: %#v", stored)
	}
}

func TestServiceRejectsExecutionResultBodiesBeforePersistence(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)
	ref := validTestManifestRef("workspace-1", "task-1", "c", 1, 11)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceManifestRef: ref,
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
	moveExecutionToRunning(t, service, record.ID)
	if _, err := service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType: EventTypeExecutionProgress,
		Result:    &warmpool.ExecuteResponse{Stdout: "must-not-enter-redis"},
	}); err == nil || !strings.Contains(err.Error(), "immutable output refs") {
		t.Fatalf("body-bearing result error = %v", err)
	}
	if store.records[record.ID].Result != nil {
		t.Fatal("body-bearing result mutated the durable record")
	}
}

func TestServiceRejectsNonInternalEventMetadata(t *testing.T) {
	store := newMemoryStore()
	service := newTestService(t, store, testMaxExecutionTimeoutSeconds)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceManifestRef: validTestManifestRef("workspace-1", "task-1", "e", 1, 17),
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = service.ApplyExecutionEvent(context.Background(), record.ID, ExecutionEventRequest{
		EventType: EventTypeExecutionClaimed,
		Metadata:  map[string]string{"caller_note": "REDIS-EVENT-METADATA-CANARY"},
	})
	if err == nil || !strings.Contains(err.Error(), "metadata") {
		t.Fatalf("ApplyExecutionEvent() error = %v, want rejected metadata", err)
	}
	if stored := store.records[record.ID]; stored.Status != ExecutionStatusQueued || stored.Metadata != nil {
		t.Fatalf("caller metadata mutated record: %#v", stored)
	}
}

type memoryStore struct {
	records   map[string]*ExecutionRecord
	requested []*ExecutionRecord
	lifecycle []string
}

func newMemoryStore() *memoryStore {
	return &memoryStore{records: map[string]*ExecutionRecord{}}
}

func (s *memoryStore) CreateExecution(_ context.Context, record *ExecutionRecord) error {
	if _, exists := s.records[record.ID]; exists {
		return ErrExecutionConflict
	}
	copied := *record
	s.records[record.ID] = &copied
	s.requested = append(s.requested, &copied)
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

func (s *memoryStore) UpdateExecution(_ context.Context, expectedRevision int64, record *ExecutionRecord, eventType string) error {
	current, exists := s.records[record.ID]
	if !exists {
		return ErrExecutionNotFound
	}
	if current.Revision != expectedRevision || record.Revision != expectedRevision+1 {
		return ErrExecutionConflict
	}
	copied := *record
	s.records[record.ID] = &copied
	s.lifecycle = append(s.lifecycle, eventType)
	return nil
}

func newTestService(t *testing.T, store Store, maxTimeout int) *Service {
	t.Helper()
	service, err := NewService(store, testExecutionPolicy(maxTimeout))
	if err != nil {
		t.Fatalf("NewService() error = %v", err)
	}
	return service
}

func testExecutionPolicy(maxTimeout int) ExecutionPolicy {
	defaultTimeout := 120
	if defaultTimeout > maxTimeout {
		defaultTimeout = maxTimeout
	}
	return ExecutionPolicy{
		DefaultTimeoutSeconds: defaultTimeout,
		MaxTimeoutSeconds:     maxTimeout,
		QueueTimeout:          5 * time.Minute,
		CompletionGrace:       time.Minute,
	}
}

func moveExecutionToRunning(t *testing.T, service *Service, id string) {
	t.Helper()
	if _, err := service.ApplyExecutionEvent(context.Background(), id, ExecutionEventRequest{EventType: EventTypeExecutionClaimed}); err != nil {
		t.Fatalf("claim execution: %v", err)
	}
	if _, err := service.ApplyExecutionEvent(context.Background(), id, ExecutionEventRequest{EventType: EventTypeExecutionStarted}); err != nil {
		t.Fatalf("start execution: %v", err)
	}
}
