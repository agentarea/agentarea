package mcpserver

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	agentsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/api"
)

type definitionArgs struct {
	DefinitionID string          `json:"definition_id"`
	Parameters   json.RawMessage `json:"parameters"`
}

func taskDefOutput(d agentsapi.TaskDef) map[string]any {
	return map[string]any{
		"id": d.ID, "name": d.Name, "description": d.Description, "agent_id": d.AgentID,
		"parameters": d.Parameters, "created_by": d.CreatedBy, "updated_at": d.UpdatedAt,
	}
}

func taskDefNotFound(err error, id string) error {
	if errors.Is(err, agentsapi.ErrNotFound) {
		return &toolError{"Task definition " + id + " not found"}
	}
	return err
}

// taskDefTools is tools/task_definitions_toolset.py.
func taskDefTools(t agentsapi.TaskDefs) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List saved tasks", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				AgentID string `json:"agent_id"`
				Limit   *int   `json:"limit"`
			}](args)
			if err != nil {
				return nil, err
			}
			limit := 100
			if in.Limit != nil {
				limit = *in.Limit
			}
			if limit < 1 || limit > 1000 {
				return nil, &toolError{"limit must be between 1 and 1000"}
			}
			var agent *string
			if in.AgentID != "" {
				agent = &in.AgentID
			}
			defs, err := t.List(ctx, c, agent, limit)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(defs))
			for i, d := range defs {
				out[i] = taskDefOutput(d)
			}
			return out, nil
		}},
		"get": {title: "Get saved task", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[definitionArgs](args)
			if err != nil {
				return nil, err
			}
			d, err := t.Get(ctx, c, in.DefinitionID)
			if err != nil {
				return nil, taskDefNotFound(err, in.DefinitionID)
			}
			return taskDefOutput(d), nil
		}},
		"create": {title: "Create saved task", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name        string          `json:"name"`
				AgentID     string          `json:"agent_id"`
				Description string          `json:"description"`
				Parameters  json.RawMessage `json:"parameters"`
			}](args)
			if err != nil {
				return nil, err
			}
			params := in.Parameters
			if len(params) == 0 || string(params) == "null" {
				params = json.RawMessage(`{}`)
			}
			doc, err := json.Marshal(map[string]any{"name": in.Name, "agent_id": in.AgentID, "description": in.Description, "parameters": params})
			if err != nil {
				return nil, err
			}
			d, err := t.Create(ctx, c, doc)
			if err != nil {
				return nil, err
			}
			return taskDefOutput(d), nil
		}},
		"run": {title: "Run saved task", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[definitionArgs](args)
			if err != nil {
				return nil, err
			}
			task, err := t.Run(ctx, c, in.DefinitionID, in.Parameters)
			if err != nil {
				return nil, taskDefNotFound(err, in.DefinitionID)
			}
			raw, err := json.Marshal(task)
			if err != nil {
				return nil, err
			}
			var body struct {
				ID          any `json:"id"`
				Status      any `json:"status"`
				ScheduledAt any `json:"scheduled_at"`
			}
			if err := json.Unmarshal(raw, &body); err != nil {
				return nil, err
			}
			return map[string]any{"run_id": body.ID, "status": body.Status, "scheduled_at": body.ScheduledAt}, nil
		}},
	}
}
