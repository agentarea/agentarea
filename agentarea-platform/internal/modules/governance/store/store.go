package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/netip"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/governance/domain"
)

//go:generate sqlc generate

// Policies reads and writes policy rules inside the session's workspace.
type Policies struct{}

// Filter narrows ListRules; a nil field does not filter.
type Filter struct {
	SubjectType, SubjectID, Effect, Target *string
	Enabled                                *bool
}

func text(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func fromText(t pgtype.Text) *string {
	if !t.Valid {
		return nil
	}
	s := t.String
	return &s
}

// naive is a timestamp without time zone holding t's wall clock.
func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.Truncate(time.Microsecond), Valid: true}
}

func params(v any) ([]byte, error) {
	if v == nil {
		v = wirejson.Object{}
	}
	return wirejson.Marshal(v, wirejson.Compact)
}

func rule(id uuid.UUID, st, sid, target, effect string, raw []byte, cond pgtype.Text, enabled bool, prio int32, managed pgtype.Text) (domain.Rule, error) {
	p, err := wirejson.Unmarshal(raw)
	if err != nil {
		return domain.Rule{}, fmt.Errorf("policy %s params: %w", id, err)
	}
	if p == nil {
		p = wirejson.Object{}
	}
	return domain.Rule{
		ID: id.String(), SubjectType: st, SubjectID: sid, Target: target, Effect: effect, Params: p,
		Condition: fromText(cond), Enabled: enabled, Priority: int64(prio), ManagedBy: fromText(managed),
	}, nil
}

// List is the workspace's rules, ordered by subject then priority. Rows of
// an effect or subject type the schema does not know are left out by the
// caller (domain.Rule.Known).
func (Policies) List(ctx context.Context, s db.Session, f Filter) ([]domain.Rule, error) {
	var enabled pgtype.Bool
	if f.Enabled != nil {
		enabled = pgtype.Bool{Bool: *f.Enabled, Valid: true}
	}
	rows, err := New(s.Q()).ListRules(ctx, ListRulesParams{
		WorkspaceID: s.Workspace().ID(), SubjectType: text(f.SubjectType), SubjectID: text(f.SubjectID),
		Effect: text(f.Effect), Target: text(f.Target), Enabled: enabled,
	})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Rule, 0, len(rows))
	for _, r := range rows {
		x, err := rule(r.ID, r.SubjectType, r.SubjectID, r.Target, r.Effect, r.Params, r.Condition, r.Enabled, r.Priority, r.ManagedBy)
		if err != nil {
			return nil, err
		}
		out = append(out, x)
	}
	return out, nil
}

// Get is the rule, false when the workspace has none with this id.
func (Policies) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Rule, bool, error) {
	r, err := New(s.Q()).GetRule(ctx, GetRuleParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Rule{}, false, nil
	}
	if err != nil {
		return domain.Rule{}, false, err
	}
	x, err := rule(r.ID, r.SubjectType, r.SubjectID, r.Target, r.Effect, r.Params, r.Condition, r.Enabled, r.Priority, r.ManagedBy)
	return x, err == nil, err
}

// Create inserts r under id, attributed to createdBy, stamped now.
func (Policies) Create(ctx context.Context, s db.Session, id uuid.UUID, createdBy string, r domain.Rule, now time.Time) (domain.Rule, error) {
	raw, err := params(r.Params)
	if err != nil {
		return domain.Rule{}, err
	}
	row, err := New(s.Q()).CreateRule(ctx, CreateRuleParams{
		ID: id, SubjectType: r.SubjectType, SubjectID: r.SubjectID, Target: r.Target, Effect: r.Effect,
		Params: raw, Condition: text(r.Condition), Enabled: r.Enabled, Priority: int32(r.Priority), //nolint:gosec // bounded by the request model
		WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, Now: naive(now), ManagedBy: text(r.ManagedBy),
	})
	if err != nil {
		return domain.Rule{}, err
	}
	return rule(row.ID, row.SubjectType, row.SubjectID, row.Target, row.Effect, row.Params, row.Condition, row.Enabled, row.Priority, row.ManagedBy)
}

// Patch holds the fields an update sets; nil leaves a column as it is.
type Patch struct {
	SubjectType, SubjectID, Target, Effect, Condition *string
	Params                                            any
	Enabled                                           *bool
	Priority                                          *int64
}

// Update applies p and stamps updated_at; false when there is no such rule.
func (Policies) Update(ctx context.Context, s db.Session, id uuid.UUID, p Patch, now time.Time) (domain.Rule, bool, error) {
	var raw []byte
	if p.Params != nil {
		b, err := params(p.Params)
		if err != nil {
			return domain.Rule{}, false, err
		}
		raw = b
	}
	var enabled pgtype.Bool
	if p.Enabled != nil {
		enabled = pgtype.Bool{Bool: *p.Enabled, Valid: true}
	}
	var prio pgtype.Int4
	if p.Priority != nil {
		prio = pgtype.Int4{Int32: int32(*p.Priority), Valid: true} //nolint:gosec // bounded by the request model
	}
	row, err := New(s.Q()).UpdateRule(ctx, UpdateRuleParams{
		SubjectType: text(p.SubjectType), SubjectID: text(p.SubjectID), Target: text(p.Target), Effect: text(p.Effect),
		Params: raw, Condition: text(p.Condition), Enabled: enabled, Priority: prio, Now: naive(now),
		WorkspaceID: s.Workspace().ID(), ID: id,
	})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Rule{}, false, nil
	}
	if err != nil {
		return domain.Rule{}, false, err
	}
	x, err := rule(row.ID, row.SubjectType, row.SubjectID, row.Target, row.Effect, row.Params, row.Condition, row.Enabled, row.Priority, row.ManagedBy)
	return x, err == nil, err
}

// Delete removes the rule; false when there was none.
func (Policies) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteRule(ctx, DeleteRuleParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

// Audit appends and reads audit_events.
type Audit struct{}

func sourceIP(s *string) (*netip.Addr, error) {
	if s == nil {
		return nil, nil
	}
	a, err := netip.ParseAddr(*s)
	if err != nil {
		return nil, fmt.Errorf("source_ip %q is not an inet: %w", *s, err)
	}
	return &a, nil
}

func metadata(m map[string]any) ([]byte, error) {
	if m == nil {
		m = map[string]any{}
	}
	return json.Marshal(m)
}

// Insert appends e, stamped now (datetime.now: the local wall clock).
func (Audit) Insert(ctx context.Context, q db.Querier, e domain.AuditEvent, now time.Time) error {
	ip, err := sourceIP(e.SourceIP)
	if err != nil {
		return err
	}
	meta, err := metadata(e.Metadata)
	if err != nil {
		return err
	}
	var changes []byte
	if e.Changes != nil {
		if changes, err = json.Marshal(e.Changes); err != nil {
			return err
		}
	}
	id, err := uuid.Parse(e.ID)
	if err != nil {
		return err
	}
	return New(q).InsertAuditEvent(ctx, InsertAuditEventParams{
		ID: id, Now: naive(now), ActorID: e.ActorID, ActorType: e.ActorType, WorkspaceID: e.WorkspaceID,
		SourceIp: ip, UserAgent: text(e.UserAgent), RequestID: text(e.RequestID), Action: e.Action,
		ResourceType: e.ResourceType, ResourceID: text(e.ResourceID), Changes: changes, EventMetadata: meta,
	})
}

// InsertOnce appends e unless its id is already there; true when written.
func (Audit) InsertOnce(ctx context.Context, q db.Querier, e domain.AuditEvent) (bool, error) {
	ip, err := sourceIP(e.SourceIP)
	if err != nil {
		return false, err
	}
	meta, err := metadata(e.Metadata)
	if err != nil {
		return false, err
	}
	id, err := uuid.Parse(e.ID)
	if err != nil {
		return false, err
	}
	n, err := New(q).InsertAuditEventOnce(ctx, InsertAuditEventOnceParams{
		ID: id, ActorID: e.ActorID, ActorType: e.ActorType, WorkspaceID: e.WorkspaceID,
		SourceIp: ip, UserAgent: text(e.UserAgent), RequestID: text(e.RequestID), Action: e.Action,
		ResourceType: e.ResourceType, ResourceID: text(e.ResourceID), EventMetadata: meta,
	})
	return n > 0, err
}

// ErrUnknownCursor is a cursor that names no event of the workspace.
var ErrUnknownCursor = errors.New("unknown audit cursor")

// Query is AuditRepository.query: newest first, the id breaking ties.
func (Audit) Query(ctx context.Context, s db.Session, f domain.AuditQuery) ([]domain.AuditEvent, error) {
	q := New(s.Q())
	p := ListAuditEventsParams{
		WorkspaceID: s.Workspace().ID(), Action: text(f.Action), ActorID: text(f.ActorID),
		ResourceType: text(f.ResourceType), ResourceID: text(f.ResourceID), Lim: int32(min(f.Limit, 100)), //nolint:gosec // at most 100
	}
	if f.Since != nil {
		p.Since = naive(*f.Since)
	}
	if f.Until != nil {
		p.Until = naive(*f.Until)
	}
	if f.Cursor != nil {
		c, err := q.GetAuditCursor(ctx, *f.Cursor)
		if errors.Is(err, pgx.ErrNoRows) || (err == nil && c.WorkspaceID != s.Workspace().ID()) {
			return nil, ErrUnknownCursor
		}
		if err != nil {
			return nil, err
		}
		p.AfterCursor, p.CursorCreatedAt, p.CursorID = true, c.CreatedAt, *f.Cursor
	}
	rows, err := q.ListAuditEvents(ctx, p)
	if err != nil {
		return nil, err
	}
	out := make([]domain.AuditEvent, 0, len(rows))
	for _, r := range rows {
		e := domain.AuditEvent{
			ID: r.ID.String(), CreatedAt: r.CreatedAt.Time, ActorID: r.ActorID, ActorType: r.ActorType,
			WorkspaceID: r.WorkspaceID, UserAgent: fromText(r.UserAgent), RequestID: fromText(r.RequestID),
			Action: r.Action, ResourceType: r.ResourceType, ResourceID: fromText(r.ResourceID),
			RawChanges: r.Changes, RawMetadata: r.EventMetadata,
		}
		if r.SourceIp != nil {
			ip := r.SourceIp.String()
			e.SourceIP = &ip
		}
		out = append(out, e)
	}
	return out, nil
}

// ResourcePage is AuditRepository.resource_events_page: rows of one resource
// type that name a resource, newest first, and how many match.
func (Audit) ResourcePage(ctx context.Context, s db.Session, resourceType string, actions []string, limit, offset int) ([]domain.AuditEvent, int64, error) {
	q := New(s.Q())
	ws := s.Workspace().ID()
	total, err := q.CountResourceAuditEvents(ctx, CountResourceAuditEventsParams{WorkspaceID: ws, Actions: actions, ResourceType: resourceType})
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.ResourceAuditEventsPage(ctx, ResourceAuditEventsPageParams{
		WorkspaceID: ws, Actions: actions, ResourceType: resourceType,
		Lim: int32(limit), Off: int32(offset), //nolint:gosec // bounded by the route
	})
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.AuditEvent, 0, len(rows))
	for _, r := range rows {
		out = append(out, domain.AuditEvent{
			ID: r.ID.String(), CreatedAt: r.CreatedAt.Time, ActorID: r.ActorID, ActorType: r.ActorType,
			WorkspaceID: ws, Action: r.Action, ResourceType: resourceType, ResourceID: fromText(r.ResourceID),
			RawMetadata: r.EventMetadata,
		})
	}
	return out, total, nil
}
