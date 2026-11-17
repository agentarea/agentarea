package service

import (
	"context"
	"errors"
	"math"
	"net/http"
	"strconv"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/store"
)

var _ agentsapi.A2ARuns = A2ARuns{}

// A2ARuns is the run side of the A2A task methods.
type A2ARuns struct{ s *Surface }

// A2A is the provider of the A2A task methods.
func (s *Surface) A2A() A2ARuns { return A2ARuns{s: s} }

func a2aView(t Task) agentsapi.A2ATask {
	return agentsapi.A2ATask{
		ID: t.ID, AgentID: t.AgentID, CreatedBy: t.CreatedBy, Status: t.Status, Result: t.Result, Error: t.Error,
		Metadata: t.Metadata, Parameters: t.Parameters, UpdatedAt: t.UpdatedAt,
	}
}

func (r A2ARuns) Start(ctx context.Context, in agentsapi.A2AStart) (string, error) {
	c, err := caller(ctx)
	if err != nil {
		return "", err
	}
	if !r.s.CreateMounted() {
		return "", errors.New("starting a run needs the run policies and the launcher, which this process was not given")
	}
	if c.BoundAgentID != in.AgentID {
		if err := r.s.RequireExecute(ctx, in.AgentID); err != nil {
			return "", err
		}
	}
	id := uuid.NewString()
	sp := runSpec{
		TaskID: id, AgentID: in.AgentID, Description: in.Description, Parameters: map[string]any{}, UserID: c.UserID,
		RequiresHumanApproval: in.RequiresHumanApproval, Metadata: in.Metadata,
		Provenance: api.TaskProvenance{OriginType: "a2a", OriginID: in.Source, SourceIdentity: in.Source},
		Credential: c.Credential,
	}
	if err := r.s.start(ctx, c.Workspace, sp); err != nil {
		switch {
		case errors.Is(err, api.ErrModelNotConfigured):
			return "", agentsapi.ErrA2AModelNotConfigured
		case errors.Is(err, api.ErrSpendCapReached):
			return "", agentsapi.ErrA2ASpendCap
		case errors.Is(err, api.ErrTaskPolicyRejected):
			return "", agentsapi.ErrA2ARejected
		}
		return "", err
	}
	return id, nil
}

func (r A2ARuns) Task(ctx context.Context, taskID string, live bool) (agentsapi.A2ATask, bool, error) {
	c, err := caller(ctx)
	if err != nil {
		return agentsapi.A2ATask{}, false, err
	}
	t, ok, err := r.s.loadTask(ctx, c.Workspace, taskID)
	if err != nil || !ok {
		return agentsapi.A2ATask{}, false, err
	}
	if live {
		t = r.s.enrich(ctx, t)
	}
	return a2aView(t), true, nil
}

func (r A2ARuns) MayAct(ctx context.Context, t agentsapi.A2ATask) error {
	c, err := caller(ctx)
	if err != nil {
		return err
	}
	ok, err := r.s.mayAct(ctx, c, Task{CreatedBy: t.CreatedBy})
	if err != nil {
		return err
	}
	if !ok {
		return httpx.HTTPError(http.StatusForbidden, notWorkspaceAdmin)
	}
	return nil
}

func (r A2ARuns) Cancel(ctx context.Context, taskID string) (bool, error) {
	c, err := caller(ctx)
	if err != nil {
		return false, err
	}
	t, ok, err := r.s.loadTask(ctx, c.Workspace, taskID)
	if err != nil || !ok {
		return false, err
	}
	if uncancellable(t.Status) || t.Status == "completed" {
		return false, nil
	}
	if t.Status == "scheduled" {
		return r.s.cancelScheduled(ctx, c.Workspace, t)
	}
	execID := t.executionID()
	if err := r.s.d.Executor.Cancel(ctx, execID); err != nil {
		r.s.d.Log.ErrorContext(ctx, "Failed to cancel workflow", "workflow_id", execID, "error", err.Error())
		return false, nil
	}
	err = r.s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		_, err := store.SetSurfaceTaskStatus(ctx, tx, t.ID, "cancelled", "", r.s.d.Now())
		return err
	})
	return err == nil, err
}

func (r A2ARuns) AgentTasks(ctx context.Context, agentID string, limit, offset int) ([]agentsapi.A2ATask, int64, error) {
	c, err := caller(ctx)
	if err != nil {
		return nil, 0, err
	}
	agent, err := uuid.Parse(agentID)
	if err != nil {
		return nil, 0, err
	}
	if offset < 0 || offset > math.MaxInt32 {
		return nil, 0, httpx.HTTPError(http.StatusBadRequest, "page offset out of range")
	}
	sess, release, err := r.s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, 0, err
	}
	defer release()
	rows, err := store.New(sess.Q()).SurfaceAgentTasks(ctx, store.SurfaceAgentTasksParams{
		WorkspaceID: c.Workspace.ID(), AgentID: agent, Status: store.Text(nil), MaxRows: int32(limit), Skip: int32(offset), //nolint:gosec // limit is bounded by the page size, offset above
	})
	if err != nil {
		return nil, 0, err
	}
	total, err := store.A2ACountAgentTasks(ctx, sess, agent)
	if err != nil {
		return nil, 0, err
	}
	out := make([]agentsapi.A2ATask, 0, len(rows))
	for _, row := range rows {
		t, err := taskOf(store.SurfaceTaskRow(row))
		if err != nil {
			return nil, 0, err
		}
		out = append(out, a2aView(t))
	}
	return out, total, nil
}

func (r A2ARuns) SetParameters(ctx context.Context, taskID string, params wirejson.Object) error {
	c, err := caller(ctx)
	if err != nil {
		return err
	}
	id, ok := parseID(taskID)
	if !ok {
		return errors.New("task id is not a UUID")
	}
	plain, ok := plainOf(params).(map[string]any)
	if !ok {
		return errors.New("task parameters are not an object")
	}
	return r.s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, tx db.Session) error {
		return store.A2ASetParameters(ctx, tx, id, plain, r.s.d.Now())
	})
}

func (r A2ARuns) Follow(ctx context.Context, t agentsapi.A2ATask, fromNow bool, emit func(string, wirejson.Object) error) error {
	c, err := caller(ctx)
	if err != nil {
		return err
	}
	req := StreamRequest{AgentID: t.AgentID, TaskID: t.ID, IncludeChunks: true, Quiet: true}
	if fromNow {
		id, ok := parseID(t.ID)
		if !ok {
			return errors.New("task id is not a UUID")
		}
		sess, release, err := r.s.d.DB.Read(ctx, c.Workspace)
		if err != nil {
			return err
		}
		end, err := store.A2AFeedEnd(ctx, sess, id)
		release()
		if err != nil {
			return err
		}
		if end >= 0 {
			req.LastEventID = strconv.FormatInt(end, 10)
		}
	}
	st, err := r.s.OpenStream(ctx, req)
	if err != nil {
		return err
	}
	return st.Run(ctx, func(_ string, frame wirejson.Object, _ string) error {
		typ, _ := frame.Get("event_type")
		data, _ := frame.Get("data")
		name, _ := typ.(string)
		obj, _ := data.(wirejson.Object)
		return emit(name, obj)
	})
}

// plainOf is a wirejson value as encoding/json writes it.
func plainOf(v any) any {
	switch x := v.(type) {
	case wirejson.Object:
		m := make(map[string]any, len(x))
		for _, kv := range x {
			m[kv.Key] = plainOf(kv.Value)
		}
		return m
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = plainOf(e)
		}
		return out
	}
	return v
}
