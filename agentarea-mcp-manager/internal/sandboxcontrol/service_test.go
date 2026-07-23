package sandboxcontrol

import (
	"context"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
	"github.com/agentarea/mcp-manager/internal/warmpool"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestServiceCreateExecutionPublishesRequestedEvent(t *testing.T) {
	store := newMemoryStore()
	events := &recordingEventBus{}
	service := NewService(store, events)

	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Runtime:              RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
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
	if len(events.requested) != 1 || events.requested[0].ID != record.ID {
		t.Fatalf("requested events = %#v", events.requested)
	}
}

func TestServiceCreatesSessionExecutionWithoutWorkspaceManifest(t *testing.T) {
	events := &recordingEventBus{}
	service := NewService(newMemoryStore(), events)

	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Runtime:     RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
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
	if len(events.requested) != 1 || events.requested[0].ID != record.ID {
		t.Fatalf("requested events = %#v", events.requested)
	}
}

func TestServiceRejectsSessionExecutionWithoutTaskIdentity(t *testing.T) {
	service := NewService(newMemoryStore(), &recordingEventBus{})

	_, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Runtime:    RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		WorkflowID: "wf-1",
		Command: warmpool.ExecuteRequest{
			CommandBody: "echo ok",
		},
	})

	if err == nil || !strings.Contains(err.Error(), "task_id and workspace_id are required") {
		t.Fatalf("CreateExecution() error = %v, want task identity requirement", err)
	}
}

func TestServiceCompletesSessionExecutionWithOutputRefs(t *testing.T) {
	store := newMemoryStore()
	events := &recordingEventBus{}
	service := NewService(store, events)
	digest := strings.Repeat("a", 64)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Runtime:     RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		WorkspaceID: "workspace-1",
		TaskID:      "task-1",
		Command:     warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatalf("CreateExecution() error = %v", err)
	}
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

func TestServiceRejectsMissingPackageInstallProfile(t *testing.T) {
	service := NewService(newMemoryStore(), &recordingEventBus{})
	_, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		WorkspaceManifestRef: validTestManifestRef("workspace-1", "task-1", "a", 1, 7),
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err == nil || !strings.Contains(err.Error(), "package_install") {
		t.Fatalf("CreateExecution() error = %v, want package_install requirement", err)
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
	events := &recordingEventBus{}
	service := NewService(store, events)
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
		Runtime:              RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
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
	if len(events.lifecycle) != 1 || events.lifecycle[0] != EventTypeExecutionCompleted {
		t.Fatalf("lifecycle events = %#v", events.lifecycle)
	}
}

func TestServiceRejectsUntrustedCompletionRefsBeforeRedisPersistence(t *testing.T) {
	store := newMemoryStore()
	service := NewService(store, &recordingEventBus{})
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
		Runtime:              RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		WorkspaceID:          baseRef.WorkspaceID,
		TaskID:               baseRef.TaskID,
		WorkspaceManifestRef: baseRef,
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
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
	if stored.Status != ExecutionStatusQueued || strings.Contains(stored.WorkspaceManifestRef.ManifestURI, "X-Amz") {
		t.Fatalf("untrusted completion mutated Redis record: %#v", stored)
	}
}

func TestServiceRejectsExecutionResultBodiesBeforePersistence(t *testing.T) {
	store := newMemoryStore()
	service := NewService(store, &recordingEventBus{})
	ref := validTestManifestRef("workspace-1", "task-1", "c", 1, 11)
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Runtime:              RuntimeSelector{PackageInstall: runtimeinfo.PackageInstallAllowed},
		WorkspaceManifestRef: ref,
		Command:              warmpool.ExecuteRequest{CommandBody: "echo ok"},
	})
	if err != nil {
		t.Fatal(err)
	}
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
	service := NewService(store, &recordingEventBus{})
	record, err := service.CreateExecution(context.Background(), ExecutionCreateRequest{
		Runtime:              RuntimeSelector{Provider: "agentarea-k8s", PackageInstall: runtimeinfo.PackageInstallAllowed},
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
