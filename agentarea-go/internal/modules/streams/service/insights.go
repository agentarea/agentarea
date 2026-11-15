package service

import (
	"cmp"
	"context"
	"slices"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// boardScan bounds the triggers one board read scans.
const boardScan = 10000

// TriggerBoard implements api.TriggerBoard over the read pool.
type TriggerBoard struct {
	DB db.Database
}

var _ api.TriggerBoard = TriggerBoard{}

func (b TriggerBoard) list(ctx context.Context, ws scope.Workspace, p store.ListTriggersParams) ([]store.Trigger, error) {
	s, release, err := b.DB.Read(ctx, ws)
	if err != nil {
		return nil, err
	}
	defer release()
	p.WorkspaceID, p.Lim = ws.ID(), boardScan
	return store.New(s.Q()).ListTriggers(ctx, p)
}

// BrokenTriggers implements api.TriggerBoard.
func (b TriggerBoard) BrokenTriggers(ctx context.Context, ws scope.Workspace, limit int) ([]api.BrokenTrigger, error) {
	rows, err := b.list(ctx, ws, store.ListTriggersParams{})
	if err != nil {
		return nil, err
	}
	var out []api.BrokenTrigger
	for _, t := range rows {
		owner := t.NeedsNewOwnerAt.Valid
		stopped := !t.IsActive && t.ConsecutiveFailures >= t.FailureThreshold
		failing := t.IsActive && t.ConsecutiveFailures > 0
		if !owner && !stopped && !failing {
			continue
		}
		bt := api.BrokenTrigger{
			ID: t.ID.String(), Name: t.Name, AgentID: t.AgentID.String(), IsActive: t.IsActive, NeedsNewOwner: owner,
			ConsecutiveFailures: int(t.ConsecutiveFailures), FailureThreshold: int(t.FailureThreshold),
		}
		if t.LastExecutionAt.Valid {
			at := t.LastExecutionAt.Time
			bt.LastExecutionAt = &at
		}
		out = append(out, bt)
	}
	slices.SortStableFunc(out, func(a, b api.BrokenTrigger) int {
		return cmp.Or(cmp.Compare(b.ConsecutiveFailures, a.ConsecutiveFailures), cmp.Compare(a.Name, b.Name))
	})
	return out[:min(len(out), max(limit, 0))], nil
}

// CronTriggers implements api.TriggerBoard.
func (b TriggerBoard) CronTriggers(ctx context.Context, ws scope.Workspace, agentID *string) ([]api.CronTrigger, error) {
	p := store.ListTriggersParams{ActiveOnly: true}
	if agentID != nil {
		u, err := uuid.Parse(*agentID)
		if err != nil {
			return nil, nil
		}
		p.AgentID = uuid.NullUUID{UUID: u, Valid: true}
	}
	rows, err := b.list(ctx, ws, p)
	if err != nil {
		return nil, err
	}
	var out []api.CronTrigger
	for _, t := range rows {
		if !t.CronExpression.Valid {
			continue
		}
		ct := api.CronTrigger{ID: t.ID.String(), Name: t.Name, AgentID: t.AgentID.String(), CronExpression: t.CronExpression.String}
		if t.Timezone.Valid {
			tz := t.Timezone.String
			ct.Timezone = &tz
		}
		out = append(out, ct)
	}
	return out, nil
}
