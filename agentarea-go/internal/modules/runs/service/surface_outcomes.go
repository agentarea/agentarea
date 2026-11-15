package service

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

// OutcomeTask is the task a task event names, as its delivery, the platform stream and its
// trigger read it. Numbers in its parameters and metadata stay json.Number.
func (s *Surface) OutcomeTask(ctx context.Context, ws scope.Workspace, taskID string) (api.OutcomeTask, bool, error) {
	id, ok := parseID(taskID)
	if !ok {
		return api.OutcomeTask{}, false, nil
	}
	var row store.OutcomeTaskRow
	var found bool
	err := s.readIn(ctx, ws, func(sess db.Session) error {
		var err error
		row, found, err = store.Runs{}.OutcomeTaskOf(ctx, sess, id)
		return err
	})
	if err != nil || !found {
		return api.OutcomeTask{}, false, err
	}
	params, err := outcomeObject(row.Parameters)
	if err != nil {
		return api.OutcomeTask{}, false, fmt.Errorf("parameters of task %s: %w", taskID, err)
	}
	meta, err := outcomeObject(row.TaskMetadata)
	if err != nil {
		return api.OutcomeTask{}, false, fmt.Errorf("metadata of task %s: %w", taskID, err)
	}
	return api.OutcomeTask{
		ID: row.ID.String(), AgentID: row.AgentID.String(), Owner: row.CreatedBy,
		OriginType: row.OriginType.String, OriginID: row.OriginID.String, CorrelationID: row.CorrelationID.String,
		Depth: int(row.Depth), Parameters: params, Metadata: meta,
	}, true, nil
}

func outcomeObject(raw []byte) (map[string]any, error) {
	if len(bytes.TrimSpace(raw)) == 0 {
		return map[string]any{}, nil
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	m, _ := v.(map[string]any)
	if m == nil {
		m = map[string]any{}
	}
	return m, nil
}
