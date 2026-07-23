package sandboxcontrol

import (
	"context"
	"fmt"
	"net/url"
	"path"
	"strings"
	"time"

	"github.com/agentarea/mcp-manager/internal/runtimeinfo"
)

type Service struct {
	store  Store
	events EventBus
}

func NewService(store Store, events EventBus) *Service {
	return &Service{store: store, events: events}
}

func (s *Service) CreateExecution(ctx context.Context, req ExecutionCreateRequest) (*ExecutionRecord, error) {
	if err := validateCreateRequest(&req); err != nil {
		return nil, err
	}
	if err := runtimeinfo.ValidatePackageInstall(req.Runtime.PackageInstall); err != nil {
		return nil, err
	}
	if req.Command.WorkspaceHydration != nil {
		return nil, fmt.Errorf("workspace_hydration is activation-only and cannot be persisted")
	}
	if req.Command.WorkspaceManifestRef != nil {
		return nil, fmt.Errorf("workspace_manifest_ref must be top-level in the execution request")
	}
	if req.WorkspaceManifestRef != nil {
		if err := req.WorkspaceManifestRef.Validate(); err != nil {
			return nil, fmt.Errorf("invalid workspace_manifest_ref: %w", err)
		}
		if req.TaskID == "" {
			req.TaskID = req.WorkspaceManifestRef.TaskID
		}
		if req.WorkspaceID == "" {
			req.WorkspaceID = req.WorkspaceManifestRef.WorkspaceID
		}
	}
	now := time.Now().UTC()
	id := newID("sexec")
	if req.WorkflowID == "" {
		req.WorkflowID = req.Command.WorkflowID
	}
	record := &ExecutionRecord{
		ID:                   id,
		SessionID:            req.SessionID,
		WorkflowID:           req.WorkflowID,
		TaskID:               req.TaskID,
		WorkspaceID:          req.WorkspaceID,
		Runtime:              req.Runtime,
		Status:               ExecutionStatusQueued,
		Command:              req.Command,
		WorkspaceManifestRef: req.WorkspaceManifestRef,
		CreatedAt:            now,
		UpdatedAt:            now,
	}
	if err := validateExecutionRecord(record); err != nil {
		return nil, err
	}
	if err := s.store.CreateExecution(ctx, record); err != nil {
		return nil, err
	}
	if err := s.events.PublishRequested(ctx, record); err != nil {
		record.Status = ExecutionStatusFailed
		record.Error = err.Error()
		record.UpdatedAt = time.Now().UTC()
		_ = s.store.UpdateExecution(ctx, record)
		return nil, err
	}
	return record, nil
}

func (s *Service) GetExecution(ctx context.Context, id string) (*ExecutionRecord, error) {
	return s.store.GetExecution(ctx, id)
}

func (s *Service) ApplyExecutionEvent(ctx context.Context, id string, event ExecutionEventRequest) (*ExecutionRecord, error) {
	if err := validateExecutionID(id); err != nil {
		return nil, err
	}
	if err := validateExecutionEvent(event); err != nil {
		return nil, err
	}
	record, err := s.store.GetExecution(ctx, id)
	if err != nil {
		return nil, err
	}
	if err := validateExecutionWorkspaceEvent(record, event); err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	if event.Status != "" {
		record.Status = event.Status
	} else {
		record.Status = statusForEventType(event.EventType, record.Status)
	}
	switch record.Status {
	case ExecutionStatusRunning:
		if record.StartedAt == nil {
			record.StartedAt = &now
		}
	case ExecutionStatusCompleted, ExecutionStatusFailed, ExecutionStatusCancelled:
		record.CompletedAt = &now
	}
	if event.Error != "" {
		record.Error = event.Error
	}
	if len(event.OutputRefs) > 0 {
		record.OutputRefs = append(record.OutputRefs, event.OutputRefs...)
	}
	if event.WorkspaceManifestRef != nil {
		record.WorkspaceManifestRef = event.WorkspaceManifestRef
	}
	if event.Result != nil {
		record.Result = event.Result
	}
	if len(event.Metadata) > 0 {
		if record.Metadata == nil {
			record.Metadata = map[string]string{}
		}
		for key, value := range event.Metadata {
			record.Metadata[key] = value
		}
	}
	record.UpdatedAt = now
	if err := validateExecutionRecord(record); err != nil {
		return nil, err
	}
	if err := s.store.UpdateExecution(ctx, record); err != nil {
		return nil, err
	}
	eventType := event.EventType
	if eventType == "" {
		eventType = eventTypeForStatus(record.Status)
	}
	if eventType != "" {
		if err := s.events.PublishLifecycleEvent(ctx, record, eventType); err != nil {
			return nil, err
		}
	}
	return record, nil
}

func validateExecutionWorkspaceEvent(record *ExecutionRecord, event ExecutionEventRequest) error {
	if record == nil {
		return fmt.Errorf("execution record is required")
	}
	baseRef := record.WorkspaceManifestRef
	nextRef := event.WorkspaceManifestRef
	if event.Result != nil {
		if event.Result.Stdout != "" || event.Result.Stderr != "" {
			return fmt.Errorf("execution result bodies must be stored as immutable output refs")
		}
		streamRefs := make([]SandboxObjectReference, 0, 2)
		if event.Result.StdoutRef != nil {
			streamRefs = append(streamRefs, *event.Result.StdoutRef)
		}
		if event.Result.StderrRef != nil {
			streamRefs = append(streamRefs, *event.Result.StderrRef)
		}
		event.OutputRefs = append(event.OutputRefs, streamRefs...)
	}
	if nextRef != nil {
		if err := nextRef.Validate(); err != nil {
			return fmt.Errorf("invalid workspace manifest completion ref: %w", err)
		}
		if nextRef.WorkspaceID != record.WorkspaceID || nextRef.TaskID != record.TaskID {
			return fmt.Errorf("workspace manifest completion identity mismatch")
		}
	}
	if len(event.OutputRefs) == 0 {
		return nil
	}
	var baseHost string
	if baseRef != nil {
		baseURI, _ := url.Parse(baseRef.ManifestURI)
		baseHost = baseURI.Host
	}
	for _, output := range event.OutputRefs {
		if err := output.Validate(); err != nil {
			return fmt.Errorf("invalid workspace output ref: %w", err)
		}
		if output.Deleted || baseRef == nil {
			continue
		}
		objectURI, _ := url.Parse(output.ObjectURI)
		expectedSuffix := "/" + path.Join(
			"workspaces",
			record.WorkspaceID,
			"tasks",
			record.TaskID,
			"objects",
			output.SHA256,
		)
		if objectURI.Host != baseHost || !strings.HasSuffix(objectURI.Path, expectedSuffix) {
			return fmt.Errorf("workspace output ref is outside the execution task prefix")
		}
	}
	return nil
}

func statusForEventType(eventType, fallback string) string {
	switch eventType {
	case EventTypeExecutionClaimed:
		return ExecutionStatusClaimed
	case EventTypeExecutionStarted, EventTypeExecutionProgress:
		return ExecutionStatusRunning
	case EventTypeExecutionCompleted:
		return ExecutionStatusCompleted
	case EventTypeExecutionFailed:
		return ExecutionStatusFailed
	case EventTypeExecutionCancelled:
		return ExecutionStatusCancelled
	default:
		return fallback
	}
}

func eventTypeForStatus(status string) string {
	switch status {
	case ExecutionStatusClaimed:
		return EventTypeExecutionClaimed
	case ExecutionStatusRunning:
		return EventTypeExecutionStarted
	case ExecutionStatusCompleted:
		return EventTypeExecutionCompleted
	case ExecutionStatusFailed:
		return EventTypeExecutionFailed
	case ExecutionStatusCancelled:
		return EventTypeExecutionCancelled
	default:
		return ""
	}
}
