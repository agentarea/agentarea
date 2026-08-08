package sandboxcontrol

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"path"
	"reflect"
	"strings"
	"time"
)

type ExecutionPolicy struct {
	DefaultTimeoutSeconds int
	MaxTimeoutSeconds     int
	QueueTimeout          time.Duration
	CompletionGrace       time.Duration
}

func (p ExecutionPolicy) Validate() error {
	if p.DefaultTimeoutSeconds <= 0 || p.MaxTimeoutSeconds <= 0 || p.DefaultTimeoutSeconds > p.MaxTimeoutSeconds {
		return fmt.Errorf("sandbox execution default/max timeout policy is invalid")
	}
	if p.QueueTimeout <= 0 || p.CompletionGrace <= 0 {
		return fmt.Errorf("sandbox execution queue timeout and completion grace must be positive")
	}
	return nil
}

type Service struct {
	store  Store
	policy ExecutionPolicy
}

func NewService(store Store, policy ExecutionPolicy) (*Service, error) {
	if store == nil {
		return nil, fmt.Errorf("sandbox execution store is required")
	}
	if err := policy.Validate(); err != nil {
		return nil, err
	}
	return &Service{store: store, policy: policy}, nil
}

func (s *Service) CreateExecution(ctx context.Context, req ExecutionCreateRequest) (*ExecutionRecord, error) {
	if req.Command.TimeoutSeconds == 0 {
		req.Command.TimeoutSeconds = s.policy.DefaultTimeoutSeconds
	}
	if err := validateCreateRequest(&req, s.policy.MaxTimeoutSeconds); err != nil {
		return nil, invalidExecution(err)
	}
	if req.Command.WorkspaceHydration != nil {
		return nil, invalidExecution(fmt.Errorf("workspace_hydration is activation-only and cannot be persisted"))
	}
	if req.Command.WorkspaceManifestRef != nil {
		return nil, invalidExecution(fmt.Errorf("workspace_manifest_ref must be top-level in the execution request"))
	}
	if req.WorkspaceManifestRef != nil {
		if err := req.WorkspaceManifestRef.Validate(); err != nil {
			return nil, invalidExecution(fmt.Errorf("invalid workspace_manifest_ref: %w", err))
		}
		if req.TaskID == "" {
			req.TaskID = req.WorkspaceManifestRef.TaskID
		}
		if req.WorkspaceID == "" {
			req.WorkspaceID = req.WorkspaceManifestRef.WorkspaceID
		}
	}
	now := time.Now().UTC()
	if req.WorkflowID == "" {
		req.WorkflowID = req.Command.WorkflowID
	}
	record := &ExecutionRecord{
		ID:                   newID("sexec"),
		Revision:             1,
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
		QueueExpiresAt:       now.Add(s.policy.QueueTimeout),
	}
	if err := validateExecutionRecord(record, s.policy.MaxTimeoutSeconds); err != nil {
		return nil, invalidExecution(err)
	}
	if err := s.store.CreateExecution(ctx, record); err != nil {
		return nil, err
	}
	return record, nil
}

func (s *Service) GetExecution(ctx context.Context, id string) (*ExecutionRecord, error) {
	if err := validateExecutionID(id); err != nil {
		return nil, invalidExecution(err)
	}
	record, err := s.store.GetExecution(ctx, id)
	if err != nil {
		return nil, err
	}
	if record.Status != ExecutionStatusQueued || time.Now().UTC().Before(record.QueueExpiresAt) {
		return record, nil
	}
	expired, expireErr := s.ApplyExecutionEvent(ctx, id, ExecutionEventRequest{
		EventType: EventTypeExecutionCancelled,
		Error:     "execution expired before a runner claimed it",
	})
	if expireErr == nil {
		return expired, nil
	}
	if !isConflict(expireErr) {
		return nil, expireErr
	}
	return s.store.GetExecution(ctx, id)
}

// CancelPendingExecution abandons only work that no runner has claimed. Once a
// command is claimed or running its outcome is no longer safe to infer from an
// HTTP client disconnect, so cancellation fails closed with a revision/state
// conflict instead of pretending the side effects did not happen.
func (s *Service) CancelPendingExecution(ctx context.Context, id, reason string) (*ExecutionRecord, error) {
	record, err := s.store.GetExecution(ctx, id)
	if err != nil {
		return nil, err
	}
	if isTerminalStatus(record.Status) {
		return record, nil
	}
	if record.Status != ExecutionStatusQueued {
		return nil, fmt.Errorf("%w: execution %s is already %s", ErrExecutionConflict, id, record.Status)
	}
	if reason == "" {
		reason = "execution cancelled before runner claim"
	}
	return s.ApplyExecutionEvent(ctx, id, ExecutionEventRequest{EventType: EventTypeExecutionCancelled, Error: reason})
}

func (s *Service) ApplyExecutionEvent(ctx context.Context, id string, event ExecutionEventRequest) (*ExecutionRecord, error) {
	if err := validateExecutionID(id); err != nil {
		return nil, invalidExecution(err)
	}
	if err := validateExecutionEvent(event); err != nil {
		return nil, invalidExecution(err)
	}
	record, err := s.store.GetExecution(ctx, id)
	if err != nil {
		return nil, err
	}
	if isTerminalStatus(record.Status) {
		if terminalReplayMatches(record, event) {
			return record, nil
		}
		return nil, fmt.Errorf("%w: execution %s is already terminal (%s)", ErrExecutionConflict, id, record.Status)
	}
	nextStatus, err := transitionStatus(record.Status, event.EventType)
	if err != nil {
		return nil, invalidExecution(err)
	}
	normalizedEvent, err := validateExecutionWorkspaceEvent(record, event)
	if err != nil {
		return nil, invalidExecution(err)
	}
	event = normalizedEvent

	next := cloneExecutionRecord(record)
	now := time.Now().UTC()
	next.Revision = record.Revision + 1
	next.Status = nextStatus
	next.UpdatedAt = now
	if event.EventType == EventTypeExecutionStarted {
		next.StartedAt = &now
		expiresAt := now.Add(time.Duration(next.Command.TimeoutSeconds)*time.Second + s.policy.CompletionGrace)
		next.ExecutionExpiresAt = &expiresAt
	}
	if isTerminalStatus(next.Status) {
		next.CompletedAt = &now
	}
	if event.Error != "" {
		next.Error = event.Error
	}
	if len(event.OutputRefs) > 0 {
		next.OutputRefs = append(next.OutputRefs, event.OutputRefs...)
	}
	if event.WorkspaceManifestRef != nil {
		next.WorkspaceManifestRef = event.WorkspaceManifestRef
	}
	if event.Result != nil {
		next.Result = event.Result
	}
	if len(event.Metadata) > 0 {
		if next.Metadata == nil {
			next.Metadata = map[string]string{}
		}
		for key, value := range event.Metadata {
			next.Metadata[key] = value
		}
	}
	if err := validateExecutionRecord(next, s.policy.MaxTimeoutSeconds); err != nil {
		return nil, invalidExecution(err)
	}
	if err := s.store.UpdateExecution(ctx, record.Revision, next, event.EventType); err != nil {
		return nil, err
	}
	return next, nil
}

func transitionStatus(current, eventType string) (string, error) {
	allowed := false
	next := ""
	switch eventType {
	case EventTypeExecutionClaimed:
		allowed, next = current == ExecutionStatusQueued, ExecutionStatusClaimed
	case EventTypeExecutionStarted:
		allowed, next = current == ExecutionStatusClaimed, ExecutionStatusRunning
	case EventTypeExecutionProgress:
		allowed, next = current == ExecutionStatusRunning, ExecutionStatusRunning
	case EventTypeExecutionCompleted:
		allowed, next = current == ExecutionStatusRunning, ExecutionStatusCompleted
	case EventTypeExecutionFailed:
		allowed, next = current == ExecutionStatusQueued || current == ExecutionStatusClaimed || current == ExecutionStatusRunning, ExecutionStatusFailed
	case EventTypeExecutionCancelled:
		allowed, next = current == ExecutionStatusQueued || current == ExecutionStatusClaimed || current == ExecutionStatusRunning, ExecutionStatusCancelled
	}
	if !allowed {
		return "", fmt.Errorf("event %s cannot transition execution from %s", eventType, current)
	}
	return next, nil
}

func terminalReplayMatches(record *ExecutionRecord, event ExecutionEventRequest) bool {
	target, err := statusForTerminalEvent(event.EventType)
	if err != nil || target != record.Status {
		return false
	}
	if event.Error != "" && event.Error != record.Error {
		return false
	}
	if event.Result != nil && !reflect.DeepEqual(event.Result, record.Result) {
		return false
	}
	if event.WorkspaceManifestRef != nil && !reflect.DeepEqual(event.WorkspaceManifestRef, record.WorkspaceManifestRef) {
		return false
	}
	if len(event.OutputRefs) > 0 && !sliceSuffixEqual(record.OutputRefs, event.OutputRefs) {
		return false
	}
	for key, value := range event.Metadata {
		if record.Metadata[key] != value {
			return false
		}
	}
	return true
}

func statusForTerminalEvent(eventType string) (string, error) {
	switch eventType {
	case EventTypeExecutionCompleted:
		return ExecutionStatusCompleted, nil
	case EventTypeExecutionFailed:
		return ExecutionStatusFailed, nil
	case EventTypeExecutionCancelled:
		return ExecutionStatusCancelled, nil
	default:
		return "", fmt.Errorf("event is not terminal")
	}
}

func sliceSuffixEqual(all, suffix []SandboxObjectReference) bool {
	if len(suffix) > len(all) {
		return false
	}
	return reflect.DeepEqual(all[len(all)-len(suffix):], suffix)
}

func cloneExecutionRecord(record *ExecutionRecord) *ExecutionRecord {
	next := *record
	next.OutputRefs = append([]SandboxObjectReference(nil), record.OutputRefs...)
	if record.Metadata != nil {
		next.Metadata = make(map[string]string, len(record.Metadata))
		for key, value := range record.Metadata {
			next.Metadata[key] = value
		}
	}
	return &next
}

func invalidExecution(err error) error {
	return fmt.Errorf("%w: %v", ErrInvalidExecution, err)
}

func isConflict(err error) bool {
	return errors.Is(err, ErrExecutionConflict)
}

func isTerminalStatus(status string) bool {
	return status == ExecutionStatusCompleted || status == ExecutionStatusFailed || status == ExecutionStatusCancelled
}

func validateExecutionWorkspaceEvent(record *ExecutionRecord, event ExecutionEventRequest) (ExecutionEventRequest, error) {
	if record == nil {
		return event, fmt.Errorf("execution record is required")
	}
	baseRef := record.WorkspaceManifestRef
	nextRef := event.WorkspaceManifestRef
	if event.Result != nil {
		if event.Result.Stdout != "" || event.Result.Stderr != "" {
			return event, fmt.Errorf("execution result bodies must be stored as immutable output refs")
		}
		if event.Result.StdoutRef != nil {
			event.OutputRefs = append(event.OutputRefs, *event.Result.StdoutRef)
		}
		if event.Result.StderrRef != nil {
			event.OutputRefs = append(event.OutputRefs, *event.Result.StderrRef)
		}
	}
	if len(event.OutputRefs) > 1 {
		unique := make([]SandboxObjectReference, 0, len(event.OutputRefs))
		seen := make(map[SandboxObjectReference]struct{}, len(event.OutputRefs))
		for _, output := range event.OutputRefs {
			if _, exists := seen[output]; exists {
				continue
			}
			seen[output] = struct{}{}
			unique = append(unique, output)
		}
		event.OutputRefs = unique
	}
	if nextRef != nil {
		if err := nextRef.Validate(); err != nil {
			return event, fmt.Errorf("invalid workspace manifest completion ref: %w", err)
		}
		if nextRef.WorkspaceID != record.WorkspaceID || nextRef.TaskID != record.TaskID {
			return event, fmt.Errorf("workspace manifest completion identity mismatch")
		}
	}
	if len(event.OutputRefs) == 0 {
		return event, nil
	}
	var baseHost string
	if baseRef != nil {
		baseURI, _ := url.Parse(baseRef.ManifestURI)
		baseHost = baseURI.Host
	}
	for _, output := range event.OutputRefs {
		if err := output.Validate(); err != nil {
			return event, fmt.Errorf("invalid workspace output ref: %w", err)
		}
		if output.Deleted || baseRef == nil {
			continue
		}
		objectURI, _ := url.Parse(output.ObjectURI)
		expectedSuffix := "/" + path.Join("workspaces", record.WorkspaceID, "tasks", record.TaskID, "objects", output.SHA256)
		if objectURI.Host != baseHost || !strings.HasSuffix(objectURI.Path, expectedSuffix) {
			return event, fmt.Errorf("workspace output ref is outside the execution task prefix")
		}
	}
	return event, nil
}
