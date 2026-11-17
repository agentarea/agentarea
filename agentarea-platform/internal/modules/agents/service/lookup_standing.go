package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
)

var _ api.Standing = (*Lookup)(nil)

func (l *Lookup) AgentStatus(ctx context.Context, ws scope.Workspace, id string) (string, bool, error) {
	parsed, err := uuid.Parse(id)
	if err != nil {
		return "", false, nil
	}
	var status string
	var ok bool
	err = l.read(ctx, ws, func(s db.Session) error {
		status, ok, err = store.TaskDefs{}.AgentStatus(ctx, s, parsed)
		return err
	})
	return status, ok, err
}

func (l *Lookup) TaskDefinition(ctx context.Context, ws scope.Workspace, id string) (api.TaskDef, bool, error) {
	parsed, err := uuid.Parse(id)
	if err != nil {
		return api.TaskDef{}, false, nil
	}
	var row store.TaskDefRow
	var ok bool
	err = l.read(ctx, ws, func(s db.Session) error {
		row, ok, err = store.TaskDefs{}.Get(ctx, s, parsed)
		return err
	})
	if err != nil || !ok {
		return api.TaskDef{}, false, err
	}
	return api.TaskDef{
		ID: row.ID.String(), Name: row.Name, Description: row.Description, AgentID: row.AgentID.String(),
		Parameters: row.Parameters, CreatedBy: row.CreatedBy, UpdatedAt: row.UpdatedAt,
	}, true, nil
}
