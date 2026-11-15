package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// Scheduling is the trigger side of the runs worker's schedule and trigger
// activities: cron rows, trigger reads, execution records (the port runs
// declares as service.Triggers). Firing is the part still missing.
type Scheduling struct {
	s *Service
}

// Scheduling returns the scheduling port of the service.
func (s *Service) Scheduling() *Scheduling { return &Scheduling{s: s} }

// CronTriggers lists every workspace's cron triggers.
func (p *Scheduling) CronTriggers(ctx context.Context) ([]api.CronRow, error) {
	q, release, err := p.s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	rows, err := p.s.st.Crons(ctx, q)
	if err != nil {
		return nil, err
	}
	out := make([]api.CronRow, 0, len(rows))
	for _, r := range rows {
		out = append(out, api.CronRow{ID: r.ID, WorkspaceID: r.WorkspaceID, CronExpression: r.Expression,
			TimeZone: r.Timezone, Active: r.Active})
	}
	return out, nil
}

// CronTrigger reads one cron trigger across workspaces; false when it is gone.
func (p *Scheduling) CronTrigger(ctx context.Context, id string) (api.CronRow, bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return api.CronRow{}, false, nil
	}
	t, ok, err := p.trigger(ctx, u)
	if err != nil || !ok {
		return api.CronRow{}, false, err
	}
	return api.CronRow{ID: t.ID, WorkspaceID: t.WorkspaceID, CronExpression: deref(t.CronExpression),
		TimeZone: deref(t.Timezone), Active: t.IsActive}, true, nil
}

// Trigger reads a trigger by id across workspaces; domain.ErrNotFound when it is gone.
func (p *Scheduling) Trigger(ctx context.Context, id string) (api.TriggerState, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return api.TriggerState{}, domain.ErrNotFound
	}
	t, ok, err := p.trigger(ctx, u)
	if err != nil {
		return api.TriggerState{}, err
	}
	if !ok {
		return api.TriggerState{}, domain.ErrNotFound
	}
	return api.TriggerState{ID: t.ID, Name: t.Name, WorkspaceID: t.WorkspaceID, Active: t.IsActive}, nil
}

// EvaluateConditions is evaluate_trigger_conditions: a trigger that is gone has its conditions unmet;
// conditions that cannot be evaluated are domain.ErrConditionUndecided, never a pass.
func (p *Scheduling) EvaluateConditions(ctx context.Context, id string, eventData map[string]any) (bool, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return false, nil
	}
	t, ok, err := p.trigger(ctx, u)
	if err != nil || !ok {
		return false, err
	}
	v, err := domain.EvaluateConditions(t.Conditions, eventData)
	return v.Met, err
}

// Fire fires a trigger for its schedule tick (execute_trigger_activity's fire, raise_retryable):
// a failure a retry may not repeat is returned unrecorded. domain.ErrNotFound for a trigger that is gone.
func (p *Scheduling) Fire(ctx context.Context, f api.TriggerFire) (api.TriggerFiring, error) {
	u, err := uuid.Parse(f.TriggerID)
	if err != nil {
		return api.TriggerFiring{}, domain.ErrNotFound
	}
	t, ok, err := p.trigger(ctx, u)
	if err != nil {
		return api.TriggerFiring{}, err
	}
	if !ok {
		return api.TriggerFiring{}, domain.ErrNotFound
	}
	ws, err := scope.NewWorkspace(t.WorkspaceID, "")
	if err != nil {
		return api.TriggerFiring{}, err
	}
	firing, err := p.s.Fire(ctx, ws, FireRequest{
		TriggerID: f.TriggerID, Data: f.Data, TaskID: f.TaskID, RaiseRetryable: true,
		Provenance: &runsapi.TaskProvenance{OriginType: f.OriginType, OriginID: f.OriginID, CorrelationID: f.CorrelationID},
	})
	if err != nil {
		return api.TriggerFiring{}, err
	}
	out := api.TriggerFiring{Outcome: firing.Outcome, Reason: firing.Reason, TaskID: firing.TaskID,
		BlockedBy: firing.BlockedBy, Verdict: firing.Verdict}
	if firing.Execution != nil {
		out.ExecutionID = firing.Execution.ID
	}
	return out, nil
}

// FireBatch is fire_trigger_batch_activity: the trigger fired once for the open batch.
func (p *Scheduling) FireBatch(ctx context.Context, b api.TriggerBatch) (int, error) {
	return p.s.Batches().Fire(ctx, openBatch(b))
}

// CloseBatch is close_trigger_batch_activity: the batch's events recorded skipped, no task.
func (p *Scheduling) CloseBatch(ctx context.Context, b api.TriggerBatch) (int, error) {
	return p.s.Batches().Close(ctx, openBatch(b))
}

func openBatch(b api.TriggerBatch) OpenBatch {
	return OpenBatch{Spec: BatchSpec{TriggerID: b.TriggerID, SubscriptionID: b.SubscriptionID, WorkspaceID: b.WorkspaceID,
		ConfiguredBy: b.ConfiguredBy, Caller: b.Caller}, WorkflowID: b.WorkflowID, EventIDs: b.EventIDs, Reason: b.Reason}
}

// RecordExecution writes the firing's trigger_executions row and updates the trigger's
// last run and failure count; a failure reaching the threshold pauses the trigger and its schedule.
func (p *Scheduling) RecordExecution(ctx context.Context, id string, r api.ExecutionRecord) (api.RecordedExecution, error) {
	u, err := uuid.Parse(id)
	if err != nil {
		return api.RecordedExecution{}, domain.ErrNotFound
	}
	t, ok, err := p.trigger(ctx, u)
	if err != nil {
		return api.RecordedExecution{}, err
	}
	if !ok {
		return api.RecordedExecution{}, domain.ErrNotFound
	}
	ws, err := scope.NewWorkspace(t.WorkspaceID, "")
	if err != nil {
		return api.RecordedExecution{}, err
	}
	now := p.s.now()
	var out api.RecordedExecution
	var disabled *domain.Trigger
	err = p.s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var taskID, errMsg *string
		var firedBy *string
		if r.TaskID != "" {
			taskID = &r.TaskID
		}
		if r.ErrorMessage != "" {
			errMsg = &r.ErrorMessage
		}
		execID, at, err := p.s.st.RecordExecution(ctx, sess, u, store.Execution{
			Status: r.Status, ExecutionTime: r.ExecutionTime, TaskID: taskID, ErrorMessage: errMsg,
			TriggerData: r.TriggerData, FiredBy: firedBy,
		}, now)
		if err != nil {
			return err
		}
		out = api.RecordedExecution{ID: execID.String(), ExecutedAt: at}
		if r.Status == "skipped" {
			return nil
		}
		success := r.Status == "success"
		if err := p.s.st.MarkExecuted(ctx, sess, u, now, success); err != nil {
			return err
		}
		if success {
			return nil
		}
		cur, ok, err := p.s.st.Get(ctx, sess, u)
		if err != nil || !ok {
			return err
		}
		if cur.IsActive && cur.Consecutive >= cur.FailureThreshold {
			cur.IsActive = false
			if _, err := p.s.st.Update(ctx, sess, cur, now); err != nil {
				return err
			}
			if _, err := p.s.st.SetSubscriptionStatus(ctx, sess, u, "paused"); err != nil {
				return err
			}
			disabled = &cur
		}
		return nil
	})
	if err != nil {
		return api.RecordedExecution{}, err
	}
	if disabled != nil {
		p.s.applySchedule(ctx, *disabled)
	}
	return out, nil
}

func (p *Scheduling) trigger(ctx context.Context, id uuid.UUID) (domain.Trigger, bool, error) {
	var t domain.Trigger
	var ok bool
	q, release, err := p.s.d.DB.Global().Read(ctx)
	if err != nil {
		return t, false, err
	}
	defer release()
	t, ok, err = p.s.st.GetAnyWorkspace(ctx, q, id)
	return t, ok, err
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
