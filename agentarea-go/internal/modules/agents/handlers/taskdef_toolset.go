package handlers

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// TaskDefsToolset is api.TaskDefs over the task definitions service.
type TaskDefsToolset struct {
	Svc      *service.Service
	TaskDefs *service.TaskDefs
}

var _ api.TaskDefs = TaskDefsToolset{}

func taskDefOut(d store.TaskDefRow) api.TaskDef {
	params := json.RawMessage(d.Parameters)
	if len(params) == 0 || string(params) == "null" {
		params = json.RawMessage("{}")
	}
	return api.TaskDef{ID: d.ID.String(), Name: d.Name, Description: d.Description, AgentID: d.AgentID.String(),
		Parameters: params, CreatedBy: d.CreatedBy, UpdatedAt: d.UpdatedAt}
}

func taskDefNotFound(err error) error {
	var nf *service.TaskDefNotFoundError
	if errors.As(err, &nf) {
		return api.ErrNotFound
	}
	return err
}

func (t TaskDefsToolset) List(ctx context.Context, c authn.Caller, agentID *string, limit int) ([]api.TaskDef, error) {
	var agent *uuid.UUID
	if agentID != nil {
		u, err := uuid.Parse(*agentID)
		if err != nil {
			return nil, err
		}
		agent = &u
	}
	rows, err := t.TaskDefs.List(ctx, c, agent, int32(limit))
	if err != nil {
		return nil, err
	}
	out := make([]api.TaskDef, len(rows))
	for i, d := range rows {
		out[i] = taskDefOut(d)
	}
	return out, nil
}

func (t TaskDefsToolset) Get(ctx context.Context, c authn.Caller, definitionID string) (api.TaskDef, error) {
	id, err := uuid.Parse(definitionID)
	if err != nil {
		return api.TaskDef{}, err
	}
	d, err := t.TaskDefs.Get(ctx, c, id)
	if err != nil {
		return api.TaskDef{}, taskDefNotFound(err)
	}
	return taskDefOut(d), nil
}

func (t TaskDefsToolset) Create(ctx context.Context, c authn.Caller, doc json.RawMessage) (api.TaskDef, error) {
	in, err := toolsetDocument(doc, taskDefCreateBody)
	if err != nil {
		return api.TaskDef{}, err
	}
	ti, _ := in.area.(taskDefInput)
	d, err := t.TaskDefs.Create(ctx, c, ti.create)
	if err != nil {
		return api.TaskDef{}, err
	}
	return taskDefOut(d), nil
}

func (t TaskDefsToolset) Run(ctx context.Context, c authn.Caller, definitionID string, parameters json.RawMessage) (any, error) {
	id, err := uuid.Parse(definitionID)
	if err != nil {
		return nil, err
	}
	var params wirejson.Object
	if len(parameters) > 0 && string(parameters) != "null" {
		v, err := wirejson.Unmarshal(parameters)
		if err != nil {
			return nil, err
		}
		var errs []httpx.FieldError
		p, _, ok := taskDefParameters(wirejson.Object{{Key: "parameters", Value: v}}, true, &errs)
		if !ok {
			return nil, httpx.Validation(errs...)
		}
		params = p
	}
	out, err := t.TaskDefs.Run(ctx, c, id, params, "mcp")
	return out, taskDefNotFound(err)
}
