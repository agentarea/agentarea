package service

import (
	"context"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store"
)

var _ api.TriggerExports = (*Service)(nil)

// ExportTriggers is TriggerRepository.list_all() for the workspace config export.
func (s *Service) ExportTriggers(ctx context.Context, ws scope.Workspace) ([]api.ExportTrigger, error) {
	var out []api.ExportTrigger
	err := s.read(ctx, ws, func(sess db.Session) error {
		ts, err := s.st.List(ctx, sess, store.Filter{Limit: 1 << 20})
		if err != nil {
			return err
		}
		for _, t := range ts {
			e := api.ExportTrigger{ID: t.ID, Name: t.Name, TriggerType: t.Type, AgentID: t.AgentID, Conditions: t.Conditions,
				TaskParameters: t.TaskParameters, IsActive: t.IsActive}
			if t.CronExpression != nil {
				e.CronExpression = *t.CronExpression
			}
			if t.Timezone != nil {
				e.Timezone = *t.Timezone
			}
			out = append(out, e)
		}
		return nil
	})
	return out, err
}
