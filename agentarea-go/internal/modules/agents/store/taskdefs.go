package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// TaskDefs is the task_definitions table.
type TaskDefs struct{}

// TaskDefRow is a task_definitions row; Parameters is the JSON as stored.
type TaskDefRow struct {
	ID          uuid.UUID
	CreatedAt   time.Time
	UpdatedAt   time.Time
	CreatedBy   string
	Name        string
	Description string
	AgentID     uuid.UUID
	Parameters  []byte
}

func taskDefRow(r TaskDefinition) TaskDefRow {
	return TaskDefRow{
		ID: r.ID, CreatedAt: r.CreatedAt.Time, UpdatedAt: r.UpdatedAt.Time, CreatedBy: r.CreatedBy,
		Name: r.Name, Description: r.Description, AgentID: r.AgentID, Parameters: r.Parameters,
	}
}

// Insert writes a new definition.
func (TaskDefs) Insert(ctx context.Context, s db.Session, createdBy string, d TaskDefRow, now time.Time) error {
	return New(s.Q()).InsertTaskDef(ctx, InsertTaskDefParams{
		ID: d.ID, Now: naive(now), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Name: d.Name,
		Description: d.Description, AgentID: d.AgentID, Parameters: d.Parameters,
	})
}

// Get is the workspace's definition, false when it has none.
func (TaskDefs) Get(ctx context.Context, s db.Session, id uuid.UUID) (TaskDefRow, bool, error) {
	r, err := New(s.Q()).GetTaskDef(ctx, GetTaskDefParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return TaskDefRow{}, false, nil
	}
	if err != nil {
		return TaskDefRow{}, false, err
	}
	return taskDefRow(r), true, nil
}

// List is the workspace's definitions, newest first, of one agent when agent is set.
func (TaskDefs) List(ctx context.Context, s db.Session, agent *uuid.UUID, limit int32) ([]TaskDefRow, error) {
	var a uuid.NullUUID
	if agent != nil {
		a = uuid.NullUUID{UUID: *agent, Valid: true}
	}
	rows, err := New(s.Q()).ListTaskDefs(ctx, ListTaskDefsParams{WorkspaceID: s.Workspace().ID(), AgentID: a, RowLimit: limit})
	if err != nil {
		return nil, err
	}
	out := make([]TaskDefRow, len(rows))
	for i, r := range rows {
		out[i] = taskDefRow(r)
	}
	return out, nil
}

// Update writes the mutable columns of d.
func (TaskDefs) Update(ctx context.Context, s db.Session, d TaskDefRow, now time.Time) error {
	return New(s.Q()).UpdateTaskDef(ctx, UpdateTaskDefParams{
		Name: d.Name, Description: d.Description, AgentID: d.AgentID, Parameters: d.Parameters,
		Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: d.ID,
	})
}

// Delete removes the definition.
func (TaskDefs) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteTaskDef(ctx, DeleteTaskDefParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

// AgentStatus is the status of the workspace's agent, false when it has none.
func (TaskDefs) AgentStatus(ctx context.Context, s db.Session, agent uuid.UUID) (string, bool, error) {
	st, err := New(s.Q()).TaskDefAgentStatus(ctx, TaskDefAgentStatusParams{WorkspaceID: s.Workspace().ID(), ID: agent})
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	return st, err == nil, err
}
