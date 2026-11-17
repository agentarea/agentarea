package service

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/store"
)

// Service is governance's use cases.
type Service struct {
	d Deps
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Service{d: d}
}

var (
	_ api.AuditWriter = (*Service)(nil)
	_ api.AuditReader = (*Service)(nil)
)

func nonEmpty(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// event is AuditService._build: the request's audit context, and how the
// caller authenticated added to the metadata without replacing a key the
// writer set. A nil caller is a writer outside a request (an activity).
func event(ctx context.Context, wsID string, c *authn.Principal, actorType, actorID, action, resourceType string, resourceID *string, meta map[string]any) domain.AuditEvent {
	m := make(map[string]any, len(meta)+3)
	for k, v := range meta {
		m[k] = v
	}
	if c != nil && c.Credential != nil {
		setDefault(m, "credential", string(c.Credential.Kind))
		setDefault(m, "surface", string(c.Credential.Surface))
		if c.Credential.KeyID != "" {
			key := "api_key_id"
			if c.Credential.Kind == authn.KindTurn {
				key = "turn_id"
			}
			setDefault(m, key, c.Credential.KeyID)
		}
	}
	if actorID == "" && c != nil {
		actorID = c.UserID
	}
	if resourceID != nil && *resourceID == "" {
		resourceID = nil
	}
	a, _ := httpx.AuditFrom(ctx)
	return domain.AuditEvent{
		ID: uuid.NewString(), ActorID: actorID, ActorType: actorType, WorkspaceID: wsID,
		SourceIP: nonEmpty(a.SourceIP), UserAgent: nonEmpty(a.UserAgent), RequestID: nonEmpty(a.RequestID),
		Action: action, ResourceType: resourceType, ResourceID: resourceID, Metadata: m,
	}
}

func setDefault(m map[string]any, k string, v any) {
	if _, ok := m[k]; !ok {
		m[k] = v
	}
}

// record is AuditService.record in the caller's transaction, then the sink.
func (sv *Service) record(ctx context.Context, s db.Session, c authn.Caller, action, resourceType string, resourceID *string, changes []map[string]any, meta map[string]any) error {
	e := event(ctx, s.Workspace().ID(), &c.Principal, "user", "", action, resourceType, resourceID, meta)
	e.Changes = changes
	now := sv.d.Now()
	if err := sv.d.Audit.Insert(ctx, s.Q(), e, now); err != nil {
		return err
	}
	e.CreatedAt = now
	sv.forward(ctx, e)
	return nil
}

// recordSwallowed is @audited's recording: a failure is logged, not raised.
func (sv *Service) recordSwallowed(ctx context.Context, s db.Session, c authn.Caller, action string, resourceID string) {
	if err := sv.record(ctx, s, c, action, "governance_policy", &resourceID, nil, nil); err != nil {
		sv.d.Log.WarnContext(ctx, "Failed to record audit event", "action", action, "resource_type", "governance_policy", "error", err)
	}
}

func (sv *Service) forward(ctx context.Context, e domain.AuditEvent) {
	if sv.d.Sink == nil {
		return
	}
	var changes any
	if e.Changes != nil {
		changes = e.Changes
	}
	row := map[string]any{
		"id": e.ID, "created_at": e.CreatedAt, "updated_at": e.CreatedAt, "actor_id": e.ActorID,
		"actor_type": e.ActorType, "workspace_id": e.WorkspaceID, "source_ip": e.SourceIP,
		"user_agent": e.UserAgent, "request_id": e.RequestID, "action": e.Action,
		"resource_type": e.ResourceType, "resource_id": e.ResourceID, "changes": changes,
		"event_metadata": e.Metadata,
	}
	if err := sv.d.Sink.Emit(ctx, row); err != nil {
		sv.d.Log.WarnContext(ctx, "Failed to forward audit event to enterprise sink", "error", err)
	}
}

// RecordOnce is AuditService.record_once: the row under rec.EventID, at most
// once, in the caller's transaction.
func (sv *Service) RecordOnce(ctx context.Context, tx db.Session, rec api.AuditRecord) error {
	if rec.ActorID == "" {
		return errors.New("audit record needs an actor_id")
	}
	if _, err := uuid.Parse(rec.EventID); err != nil {
		return err
	}
	actorType := rec.ActorType
	if actorType == "" {
		actorType = "user"
	}
	e := event(ctx, tx.Workspace().ID(), nil, actorType, rec.ActorID, rec.Action, rec.ResourceType, nonEmpty(rec.ResourceID), rec.Metadata)
	e.ID = rec.EventID
	inserted, err := sv.d.Audit.InsertOnce(ctx, tx.Q(), e)
	if err != nil || !inserted {
		return err
	}
	e.CreatedAt = sv.d.Now()
	sv.forward(ctx, e)
	return nil
}

// ErrUnknownCursor is a cursor naming no event of the workspace.
var ErrUnknownCursor = store.ErrUnknownCursor

// AuditLogs is one page of the workspace's audit events, newest first.
func (sv *Service) AuditLogs(ctx context.Context, c authn.Caller, q domain.AuditQuery) ([]domain.AuditEvent, error) {
	s, done, err := sv.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	defer done()
	return sv.d.Audit.Query(ctx, s, q)
}

// secretAuditor records the secret catalog's rows for one caller
// (SecretCatalogService._audit): failures propagate.
type secretAuditor struct {
	sv *Service
	c  authn.Caller
}

func (a secretAuditor) Record(ctx context.Context, s db.Session, e secrets.AuditEntry) error {
	var changes []map[string]any
	if e.Changes != nil {
		changes = make([]map[string]any, len(e.Changes))
		for i, ch := range e.Changes {
			changes[i] = map[string]any{"field": ch.Field, "before": ch.Before, "after": ch.After}
		}
	}
	return a.sv.record(ctx, s, a.c, e.Action, "secret", &e.SecretID, changes, map[string]any{"resource_name": e.ResourceName})
}

// recordSystem records a row for a user acting outside a request's
// credential (a workspace being created).
func (sv *Service) recordSystem(ctx context.Context, s db.Session, userID, action, resourceID string) error {
	return sv.record(ctx, s, authn.Caller{Principal: authn.Principal{UserID: userID}, Workspace: s.Workspace()}, action, "governance_policy", &resourceID, nil, nil)
}

// ResourceEvents is one page of a resource type's audit rows in the caller's
// session.
func (sv *Service) ResourceEvents(ctx context.Context, s db.Session, q api.AuditPage) ([]api.AuditEntry, int64, error) {
	rows, total, err := sv.d.Audit.ResourcePage(ctx, s, q.ResourceType, q.Actions, q.Limit, q.Offset)
	if err != nil {
		return nil, 0, err
	}
	out := make([]api.AuditEntry, len(rows))
	for i, r := range rows {
		out[i] = api.AuditEntry{ID: r.ID, CreatedAt: r.CreatedAt, ActorType: r.ActorType, ActorID: r.ActorID, Action: r.Action, Metadata: r.RawMetadata}
		if r.ResourceID != nil {
			out[i].ResourceID = *r.ResourceID
		}
	}
	return out, total, nil
}
