package store

import (
	"context"
	"encoding/json"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// A2ACountAgentTasks is count_agent_tasks: the agent's tasks in the session's workspace.
func A2ACountAgentTasks(ctx context.Context, s db.Session, agentID uuid.UUID) (int64, error) {
	var n int64
	err := s.Q().QueryRow(ctx, `SELECT count(*) FROM tasks WHERE workspace_id = $1 AND agent_id = $2`,
		s.Workspace().ID(), agentID).Scan(&n)
	return n, err
}

// A2AFeedEnd is the last feed position of a task's log; -1 while it is empty.
func A2AFeedEnd(ctx context.Context, s db.Session, taskID uuid.UUID) (int64, error) {
	var n int64
	err := s.Q().QueryRow(ctx, `SELECT COALESCE(max(seq), -1) FROM task_conversation_entries
WHERE task_id = $1 AND workspace_id = $2 AND (kind = 'event' OR (kind = 'message' AND role = 'user'))`,
		taskID, s.Workspace().ID()).Scan(&n)
	return n, err
}

// A2ASetParameters replaces a task's parameters (TaskUpdate(task_parameters=...)).
func A2ASetParameters(ctx context.Context, s db.Session, taskID uuid.UUID, params map[string]any, now time.Time) error {
	raw, err := json.Marshal(params)
	if err != nil {
		return err
	}
	_, err = s.Q().Exec(ctx, `UPDATE tasks SET parameters = $3::jsonb, updated_at = $4 WHERE id = $1 AND workspace_id = $2`,
		taskID, s.Workspace().ID(), string(raw), naive(now))
	return err
}
