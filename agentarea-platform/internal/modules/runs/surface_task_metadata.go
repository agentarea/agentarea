package runs

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// TaskMetadata reads a workspace task's metadata JSON (governance's run
// policy snapshots).
func (m *Surface) TaskMetadata(ctx context.Context, ws scope.Workspace, taskID string) ([]byte, bool, error) {
	return m.s.TaskMetadata(ctx, ws, taskID)
}
