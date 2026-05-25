package sandboxcontrol

import (
	"context"
	"fmt"
	"time"
)

type Service struct {
	store  Store
	events EventBus
}

func NewService(store Store, events EventBus) *Service {
	return &Service{store: store, events: events}
}

func (s *Service) CreateExecution(ctx context.Context, req ExecutionCreateRequest) (*ExecutionRecord, error) {
	if req.Command.ScriptContent == "" || req.Command.ScriptName == "" {
		return nil, fmt.Errorf("command.script_content and command.script_name are required")
	}
	now := time.Now().UTC()
	id := newID("sexec")
	if req.WorkflowID == "" {
		req.WorkflowID = req.Command.WorkflowID
	}
	record := &ExecutionRecord{
		ID:          id,
		SessionID:   req.SessionID,
		WorkflowID:  req.WorkflowID,
		TaskID:      req.TaskID,
		WorkspaceID: req.WorkspaceID,
		Runtime:     req.Runtime,
		Status:      ExecutionStatusQueued,
		Command:     req.Command,
		Metadata:    req.Metadata,
		InputRefs:   req.InputRefs,
		CreatedAt:   now,
		UpdatedAt:   now,
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
	record, err := s.store.GetExecution(ctx, id)
	if err != nil {
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
