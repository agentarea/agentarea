package service

import (
	"context"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	govapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
)

// audit is @audited's record (audit/decorator.py): written after the action
// in its transaction; a failure is logged and never fails the action.
func (s *Service) audit(ctx context.Context, sess db.Session, c authn.Caller, action, resourceType, resourceID string) {
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
		EventID: uuid.NewString(), Action: action, ResourceType: resourceType, ResourceID: resourceID,
		ActorType: "user", ActorID: c.UserID, Metadata: meta,
	})
	if err != nil && s.d.Log != nil {
		s.d.Log.WarnContext(ctx, "Failed to record audit event", "action", action, "resource_type", resourceType, "error", err.Error())
	}
}

// Audit is audit for the other route groups' services.
func (s *Service) Audit(ctx context.Context, sess db.Session, c authn.Caller, action, resourceType, resourceID string) {
	s.audit(ctx, sess, c, action, resourceType, resourceID)
}

// UseAudit sets the audit writer of a module built before governance.
func (s *Service) UseAudit(a govapi.AuditWriter) { s.d.Audit = a }
