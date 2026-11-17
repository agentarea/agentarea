package service

import (
	"context"
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// TaskMetadata is a workspace task's metadata JSON; false when there is no such task.
func (s *Surface) TaskMetadata(ctx context.Context, ws scope.Workspace, taskID string) ([]byte, bool, error) {
	t, ok, err := s.loadTask(ctx, ws, taskID)
	if err != nil || !ok {
		return nil, false, err
	}
	if t.Metadata == nil {
		return nil, true, nil
	}
	raw, err := json.Marshal(t.Metadata)
	return raw, err == nil, err
}
