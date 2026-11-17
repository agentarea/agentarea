package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// StartDefinition is TaskDefinitionService.run's TaskService.start_run.
func (s *Surface) StartDefinition(ctx context.Context, c authn.Caller, in api.DefinitionRun) (wirejson.Object, error) {
	if !s.CreateMounted() {
		return nil, errors.New("starting runs is not wired")
	}
	if _, err := s.definition(ctx, c.Workspace, in.AgentID); err != nil {
		var r *Refusal
		if errors.As(err, &r) {
			return nil, r.HTTP()
		}
		return nil, s.internal(ctx, "Task creation failed", err)
	}
	params := map[string]any{}
	for k, v := range in.Parameters {
		params[k] = v
	}
	taskID := uuid.NewString()
	prov := provenanceOf(c)
	prov.TaskDefinitionID = in.DefinitionID
	spec := runSpec{
		TaskID: taskID, AgentID: in.AgentID, Description: in.Description, Parameters: params,
		UserID: c.UserID, Metadata: map[string]any{"created_via": in.CreatedVia}, Provenance: prov, Credential: c.Credential,
	}
	if err := s.start(ctx, c.Workspace, spec); err != nil {
		var r *Refusal
		if errors.As(err, &r) {
			return nil, r.HTTP()
		}
		return nil, s.internal(ctx, "Task creation failed", err)
	}
	t, ok, err := s.loadTask(ctx, c.Workspace, taskID)
	if err != nil {
		return nil, s.internal(ctx, "Failed to read the created task", err)
	}
	if !ok {
		return nil, s.internal(ctx, "Failed to read the created task", fmt.Errorf("task %s vanished after creation", taskID))
	}
	return TaskResponseJSON(t, c), nil
}
