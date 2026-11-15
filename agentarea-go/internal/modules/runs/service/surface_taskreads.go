package service

import (
	"context"
	"errors"
	"fmt"
	"strconv"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/store"
)

var (
	_ api.TaskReads   = (*Surface)(nil)
	_ api.FiringTasks = (*Surface)(nil)
)

func parseIDs(ids []string) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(ids))
	for _, id := range ids {
		if u, ok := parseID(id); ok {
			out = append(out, u)
		}
	}
	return out
}

func (s *Surface) readIn(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

// Statuses is TaskRepository.statuses.
func (s *Surface) Statuses(ctx context.Context, ws scope.Workspace, ids []string) (map[string]string, error) {
	parsed := parseIDs(ids)
	if len(parsed) == 0 {
		return map[string]string{}, nil
	}
	var out map[string]string
	err := s.readIn(ctx, ws, func(sess db.Session) error {
		var err error
		out, err = store.Runs{}.TaskStatuses(ctx, sess, parsed)
		return err
	})
	return out, err
}

// Costs is _costs_by_task: own_cost, else total_cost, else 0. A stored cost
// that is not a number counts as absent instead of failing the page.
func (s *Surface) Costs(ctx context.Context, ws scope.Workspace, ids []string) (map[string]float64, error) {
	parsed := parseIDs(ids)
	if len(parsed) == 0 {
		return map[string]float64{}, nil
	}
	var rows map[string]store.TaskCostText
	if err := s.readIn(ctx, ws, func(sess db.Session) error {
		var err error
		rows, err = store.Runs{}.TaskCosts(ctx, sess, parsed)
		return err
	}); err != nil {
		return nil, err
	}
	out := make(map[string]float64, len(rows))
	for id, c := range rows {
		out[id] = 0
		for _, raw := range []string{c.OwnCost, c.TotalCost} {
			if v, err := strconv.ParseFloat(raw, 64); err == nil {
				out[id] = v
				break
			}
		}
	}
	return out, nil
}

// Task is TaskService.get_task as a retried firing reads it.
func (s *Surface) Task(ctx context.Context, ws scope.Workspace, id string) (api.StoredTask, bool, error) {
	if _, ok := parseID(id); !ok {
		return api.StoredTask{}, false, nil
	}
	var t store.StoredTask
	err := s.readIn(ctx, ws, func(sess db.Session) error {
		var err error
		t, err = store.Runs{}.TaskToLaunch(ctx, sess, id)
		return err
	})
	if errors.Is(err, store.ErrTaskNotFound) {
		return api.StoredTask{}, false, nil
	}
	if err != nil {
		return api.StoredTask{}, false, err
	}
	return api.StoredTask{Status: t.Status, ExecutionID: t.ExecutionID}, true, nil
}

// RestartUndispatched is restart_undispatched_task: the stored row keeps its
// ask; message is what the run is started with.
func (s *Surface) RestartUndispatched(ctx context.Context, ws scope.Workspace, id, message string) error {
	if s.d.Launcher == nil {
		return errors.New("restarting a task needs the run launcher")
	}
	var t store.StoredTask
	if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, tx db.Session) error {
		var err error
		t, err = store.Runs{}.TaskToLaunch(ctx, tx, id)
		if err != nil {
			return err
		}
		if (t.Status != "pending" && t.Status != "failed") || t.ExecutionID != "" {
			return fmt.Errorf("task %s has started before; refusing to start it again", t.ID)
		}
		if !hasEffectivePolicy(t.Metadata) {
			return fmt.Errorf("task %s has no stored effective policy to start under", t.ID)
		}
		_, err = store.SetSurfaceTaskStatus(ctx, tx, t.ID, "pending", "", s.d.Now())
		return err
	}); err != nil {
		return err
	}
	t.Status, t.Description = "pending", message
	return s.launch(ctx, ws, t)
}

// OpenRunFrom is _run_still_going: a stored status can outlive its run, so the
// workflow is asked; a task whose workflow never started runs nothing.
func (s *Surface) OpenRunFrom(ctx context.Context, ws scope.Workspace, originType, originID string) (string, error) {
	var runs []store.UnfinishedRun
	if err := s.readIn(ctx, ws, func(sess db.Session) error {
		var err error
		runs, err = store.Runs{}.UnfinishedRunsFrom(ctx, sess, originType, originID)
		return err
	}); err != nil {
		return "", err
	}
	for _, r := range runs {
		if r.ExecutionID == "" {
			continue
		}
		if s.d.Executor == nil {
			return r.TaskID, nil
		}
		res, err := s.d.Executor.Status(ctx, r.ExecutionID)
		if errors.Is(err, durable.ErrNotFound) {
			continue
		}
		if err != nil {
			return "", err
		}
		if res.Status == durable.StatusRunning {
			return r.TaskID, nil
		}
	}
	return "", nil
}

// Origin is a task's provenance as the trigger loop guard walks it.
func (s *Surface) Origin(ctx context.Context, ws scope.Workspace, taskID string) (api.TaskOrigin, bool, error) {
	id, ok := parseID(taskID)
	if !ok {
		return api.TaskOrigin{}, false, nil
	}
	var row store.TaskOriginRow
	var found bool
	err := s.readIn(ctx, ws, func(sess db.Session) error {
		var err error
		row, found, err = store.Runs{}.TaskOriginOf(ctx, sess, id)
		return err
	})
	if err != nil || !found {
		return api.TaskOrigin{}, false, err
	}
	return api.TaskOrigin{OriginType: row.OriginType, OriginID: row.OriginID, CausationID: row.CausationID}, true, nil
}
