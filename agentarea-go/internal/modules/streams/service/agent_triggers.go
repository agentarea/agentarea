package service

import (
	"context"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// validateNew is the configuration checks of Create that need neither the agent nor the store:
// the rules of validate_trigger_configuration, cron, session, batch, reserved parameters and the
// event filter. It returns the trigger with its cron fields trimmed and the stored filter.
func (s *Service) validateNew(n domain.NewTrigger) (domain.NewTrigger, map[string]any, error) {
	if err := n.Validate(); err != nil {
		return n, nil, err
	}
	if n.Type == domain.TypeCron {
		expr, tz := strings.TrimSpace(*n.CronExpression), strings.TrimSpace(*n.Timezone)
		if err := CheckCron(expr); err != nil {
			return n, nil, err
		}
		if err := CheckTimezone(tz); err != nil {
			return n, nil, err
		}
		n.CronExpression, n.Timezone = &expr, &tz
	}
	if err := domain.ValidateSession(n.Session); err != nil {
		return n, nil, err
	}
	if err := domain.ValidateBatch(n.Batch, s.d.Settings.BatchMaxEvents, n.TaskParameters, n.TaskDefinitionID); err != nil {
		return n, nil, err
	}
	if err := domain.RefuseReserved(n.TaskParameters); err != nil {
		return n, nil, err
	}
	var filter map[string]any
	if n.Type == domain.TypeStream {
		f, err := domain.ParseEventFilter(anyMap(n.EventFilter))
		if err != nil {
			return n, nil, err
		}
		filter = f.Dump()
	}
	return n, filter, nil
}

// CheckNew is validate_configuration plus the stream rules of create_trigger_from_spec: the
// configuration, the stream existing in the workspace and the caller reading it. The agent is
// not read, it does not exist yet.
func (s *Service) CheckNew(ctx context.Context, c authn.Caller, n domain.NewTrigger) error {
	if _, _, err := s.validateNew(n); err != nil {
		return err
	}
	if n.Type != domain.TypeStream || n.StreamID == nil {
		return nil
	}
	id, err := uuid.Parse(*n.StreamID)
	if err != nil {
		return streamMissing(*n.StreamID)
	}
	var ok bool
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		var rerr error
		ok, rerr = s.st.StreamExists(ctx, sess, id)
		return rerr
	})
	if err != nil {
		return err
	}
	if !ok {
		return streamMissing(*n.StreamID)
	}
	return s.perms.Require(ctx, c, "read", "stream", id.String())
}
