package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

// eventSource is the source of every task event a run publishes.
const eventSource = "agentarea-worker"

// Service holds the use cases of the run's activities, one file per Python activity file.
type Service struct {
	d     Deps
	store store.Runs
}

// New is the service over its ports; Now and Log default to the clock and slog.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	return &Service{d: d}
}

func (s *Service) now() time.Time { return s.d.Now().UTC() }

// workspace is the principal's workspace; an activity fails when the principal is incomplete.
func workspace(p Principal) (scope.Workspace, error) {
	if p.WorkspaceID == "" || p.UserID == "" || p.AgentID == "" {
		return scope.Workspace{}, nonRetryable("ValueError", fmt.Sprintf("the activity's principal is incomplete (workspace %q, user %q, agent %q)", p.WorkspaceID, p.UserID, p.AgentID), nil)
	}
	return scope.NewWorkspace(p.WorkspaceID, "")
}

func nonRetryable(errType, msg string, cause error, details ...any) *durable.ApplicationError {
	return &durable.ApplicationError{Type: errType, Message: msg, NonRetryable: true, Cause: cause, Details: details}
}

// taskNotFound turns the store's missing task into the final TaskNotFound.
func taskNotFound(err error) error {
	if errors.Is(err, store.ErrTaskNotFound) {
		return nonRetryable("TaskNotFound", err.Error(), err)
	}
	return err
}

// taskEvent is the broker envelope of one task event (task_stream.task_event).
func taskEvent(taskID, workspaceID, eventType, eventID string, ts time.Time, data map[string]any, seq *int64) events.IntegrationEvent {
	ext := map[string]string{}
	if workspaceID != "" {
		ext["workspace"] = workspaceID
	}
	if seq != nil {
		ext["seq"] = fmt.Sprint(*seq)
	}
	return events.IntegrationEvent{
		ID: eventID, Type: eventType, Source: eventSource, Subject: taskID, Time: ts, Data: data, Extensions: ext,
	}
}

func (s *Service) putText(ctx context.Context, key, body, contentType string) error {
	return s.d.Blob.Put(ctx, key, bytes.NewReader([]byte(body)), int64(len(body)), blob.PutOptions{ContentType: contentType})
}

func (s *Service) getText(ctx context.Context, key string) (string, error) {
	r, _, err := s.d.Blob.Get(ctx, key)
	if err != nil {
		return "", err
	}
	defer func() { _ = r.Close() }()
	b, err := io.ReadAll(r)
	return string(b), err
}

// jsonValue is v as plain JSON values (maps, slices, strings, numbers).
func jsonValue(v map[string]any) map[string]any {
	b, err := json.Marshal(v)
	if err != nil {
		return v
	}
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		return v
	}
	return out
}

func newID() string { return uuid.NewString() }
