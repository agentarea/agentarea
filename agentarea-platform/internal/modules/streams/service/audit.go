package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	govapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
)

// audit is @audited's record (audit/decorator.py): written after the action in its
// transaction; a failure is logged and never fails the action.
func (s *Service) audit(ctx context.Context, sess db.Session, c authn.Caller, action, resourceID string) {
	if s.d.Audit == nil {
		return
	}
	meta := map[string]any{}
	if cr := c.Credential; cr != nil {
		meta["credential"] = string(cr.Kind)
		meta["surface"] = string(cr.Surface)
		if cr.KeyID != "" {
			key := "api_key_id"
			if cr.Kind == authn.KindTurn {
				key = "turn_id"
			}
			meta[key] = cr.KeyID
		}
	}
	err := s.d.Audit.RecordOnce(ctx, sess, govapi.AuditRecord{
		EventID: uuid.NewString(), Action: action, ResourceType: "trigger", ResourceID: resourceID,
		ActorType: "user", ActorID: c.UserID, Metadata: meta,
	})
	if err != nil {
		s.log.WarnContext(ctx, "Failed to record audit event", "action", action, "resource_type", "trigger", "error", err.Error())
	}
}
