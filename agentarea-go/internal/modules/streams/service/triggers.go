package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/store"
)

// Service is TriggerService's routes-facing use cases (libs/triggers trigger_service.py).
type Service struct {
	d     Deps
	st    store.Triggers
	ss    store.Streams
	perms authz.Permissions
	log   *slog.Logger
	hub   *noticeHub
}

var _ api.Triggers = (*Service)(nil)

// New builds the service; Now and Log default to the clock and slog.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.Settings == (Settings{}) {
		d.Settings = DefaultSettings()
	}
	s := &Service{d: d, perms: authz.NewPermissions(d.Graph, d.Log), log: d.Log}
	if d.Broker != nil {
		s.hub = &noticeHub{broker: d.Broker, log: d.Log, queues: map[string]map[chan Notice]bool{}}
	}
	return s
}

func (s *Service) now() time.Time { return s.d.Now().UTC() }

func callerOf(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

func (s *Service) read(ctx context.Context, ws scope.Workspace, fn func(db.Session) error) error {
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

// Patch is the fields of a TriggerUpdate the route sent; nil means unchanged. TaskDefinitionID,
// Session and Batch are cleared when their *Set flag is true and the value is nil (sent as null).
type Patch struct {
	Name              *string
	Description       *string
	AgentID           *string
	Enabled           *bool
	Conditions        map[string]any
	TaskParameters    map[string]any
	TaskDefinitionID  *string
	TaskDefinitionSet bool
	FailureThreshold  *int
	CronExpression    *string
	Timezone          *string
	Session           *domain.Session
	SessionSet        bool
	Batch             *domain.Batch
	BatchSet          bool
	EventFilter       map[string]any
}

func (s *Service) requireAgent(ctx context.Context, ws scope.Workspace, agentID string) error {
	ok, err := s.d.Agents.AgentExists(ctx, ws, agentID)
	if err != nil {
		return err
	}
	if !ok {
		return domain.Invalid(fmt.Sprintf("Agent with ID %s does not exist", agentID))
	}
	return nil
}

func streamMissing(id string) error {
	return domain.Invalid(fmt.Sprintf("Stream %s does not exist in this workspace", id))
}

// Create is create_trigger plus the route's checks that run before it (triggers.py create, _trigger_creation.py).
func (s *Service) Create(ctx context.Context, n domain.NewTrigger) (domain.Trigger, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Trigger{}, err
	}
	if c.UserID == "" {
		return domain.Trigger{}, domain.Invalid("User ID is required to create a trigger")
	}
	ws := c.Workspace
	if n.StreamID != nil {
		if err := s.perms.Require(ctx, c, "read", "stream", *n.StreamID); err != nil {
			return domain.Trigger{}, err
		}
	}
	if err := s.perms.Require(ctx, c, "execute", "agent", n.AgentID); err != nil {
		return domain.Trigger{}, err
	}
	if err := s.requireAgent(ctx, ws, n.AgentID); err != nil {
		return domain.Trigger{}, err
	}
	n, filter, err := s.validateNew(n)
	if err != nil {
		return domain.Trigger{}, err
	}
	if err := s.checkConditionModels(ctx, ws, n.Conditions); err != nil {
		return domain.Trigger{}, err
	}
	now := s.now()
	id := uuid.New()
	t := domain.Trigger{
		ID: id.String(), WorkspaceID: ws.ID(), Name: n.Name, Description: n.Description, AgentID: n.AgentID,
		TaskDefinitionID: n.TaskDefinitionID, Type: n.Type, IsActive: n.Enabled, TaskParameters: n.TaskParameters,
		Conditions: n.Conditions, FailureThreshold: n.FailureThreshold, CronExpression: n.CronExpression,
		Timezone: n.Timezone, Session: n.Session, Batch: n.Batch, CreatedBy: c.UserID, CreatedAt: now, UpdatedAt: now,
	}
	if t.FailureThreshold == 0 {
		t.FailureThreshold = 5
	}
	if t.TaskParameters == nil {
		t.TaskParameters = map[string]any{}
	}
	if t.Conditions == nil {
		t.Conditions = map[string]any{}
	}
	subID := uuid.New()
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		var streamID uuid.UUID
		if n.Type == domain.TypeStream {
			if streamID, err = uuid.Parse(*n.StreamID); err != nil {
				return streamMissing(*n.StreamID)
			}
			ok, err := s.st.StreamExists(ctx, sess, streamID)
			if err != nil {
				return err
			}
			if !ok {
				return streamMissing(*n.StreamID)
			}
		}
		if err := s.st.Insert(ctx, sess, id, t, now); err != nil {
			return err
		}
		if n.Type == domain.TypeStream {
			if err := s.st.InsertSubscription(ctx, sess, subID, streamID, id, filter, subStatus(n.Enabled), c.UserID, now); err != nil {
				return err
			}
			if err := subscriptionsChanged(ctx, sess, c.UserID, streamID.String()); err != nil {
				return err
			}
		}
		s.audit(ctx, sess, c, "trigger.create", id.String())
		return nil
	})
	if err != nil {
		return domain.Trigger{}, err
	}
	if err := authz.GrantResourceOwner(ctx, s.d.Graph, id.String(), ws.ID(), authz.UserSubject(c.UserID), authz.OwnerRelations()); err != nil {
		return domain.Trigger{}, err
	}
	s.applySchedule(ctx, t)
	return s.Get(ctx, id.String())
}

// anyMap keeps a nil map nil, so an absent filter parses as the empty filter.
func anyMap(m map[string]any) any {
	if m == nil {
		return nil
	}
	return m
}

func subStatus(active bool) string {
	if active {
		return "active"
	}
	return "paused"
}

// Get returns the trigger with its stream binding; domain.ErrNotFound for an unknown id.
func (s *Service) Get(ctx context.Context, id string) (domain.Trigger, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Trigger{}, err
	}
	u, err := uuid.Parse(id)
	if err != nil {
		return domain.Trigger{}, domain.ErrNotFound
	}
	var out domain.Trigger
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		t, ok, err := s.st.Get(ctx, sess, u)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrNotFound
		}
		b, err := s.st.Binding(ctx, sess, u)
		if err != nil {
			return err
		}
		t.Binding = b
		out = t
		return nil
	})
	return out, err
}

// List returns the workspace's triggers with their bindings.
func (s *Service) List(ctx context.Context, f store.Filter) ([]domain.Trigger, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	var out []domain.Trigger
	err = s.read(ctx, c.Workspace, func(sess db.Session) error {
		ts, err := s.st.List(ctx, sess, f)
		if err != nil {
			return err
		}
		for i := range ts {
			id, err := uuid.Parse(ts[i].ID)
			if err != nil {
				return err
			}
			if ts[i].Binding, err = s.st.Binding(ctx, sess, id); err != nil {
				return err
			}
		}
		out = ts
		return nil
	})
	return out, err
}

// taskDefinitionAfter is _task_definition_after: the saved task once p is applied.
func taskDefinitionAfter(cur domain.Trigger, p Patch) *string {
	if p.TaskDefinitionSet {
		return p.TaskDefinitionID
	}
	return cur.TaskDefinitionID
}

// validateUpdate is _validate_trigger_update: only what the patch sends is checked, so a
// row stored before a rule existed still takes edits that leave it alone.
func (s *Service) validateUpdate(ctx context.Context, c authn.Caller, cur domain.Trigger, p Patch) error {
	if p.Name != nil && isBlank(*p.Name) {
		return domain.Invalid("Trigger name cannot be empty")
	}
	if p.AgentID != nil {
		if err := s.requireAgent(ctx, c.Workspace, *p.AgentID); err != nil {
			return err
		}
	}
	if p.FailureThreshold != nil && (*p.FailureThreshold < 1 || *p.FailureThreshold > 100) {
		return domain.Invalid("failure_threshold must be between 1 and 100")
	}
	if p.CronExpression != nil {
		if err := CheckCron(*p.CronExpression); err != nil {
			return err
		}
	}
	if p.Timezone != nil {
		if err := CheckTimezone(strings.TrimSpace(*p.Timezone)); err != nil {
			return err
		}
	}
	if p.Conditions != nil {
		if err := domain.CheckConditions(p.Conditions); err != nil {
			return err
		}
		if err := s.checkConditionModels(ctx, c.Workspace, p.Conditions); err != nil {
			return err
		}
	}
	params := cur.TaskParameters
	if p.TaskParameters != nil {
		params = p.TaskParameters
	}
	if p.Session != nil {
		if cur.Type != domain.TypeStream {
			return domain.Invalid("session applies only to stream triggers")
		}
		if err := domain.ValidateSession(p.Session); err != nil {
			return err
		}
	}
	if p.Batch != nil {
		if cur.Type != domain.TypeStream {
			return domain.Invalid("only a stream trigger takes a batch")
		}
		if err := domain.ValidateBatch(p.Batch, s.d.Settings.BatchMaxEvents, params, taskDefinitionAfter(cur, p)); err != nil {
			return err
		}
	}
	if p.EventFilter != nil {
		if cur.Type != domain.TypeStream {
			return domain.Invalid("event_filter applies only to stream triggers")
		}
		if _, err := domain.ParseEventFilter(p.EventFilter); err != nil {
			return err
		}
	}
	if cur.Type == domain.TypeCron && (p.TaskParameters != nil || p.TaskDefinitionSet) && taskDefinitionAfter(cur, p) == nil {
		if text, _ := params["text"].(string); isBlank(text) {
			return domain.Invalid("Task text is required for CRON triggers")
		}
	}
	return nil
}

func isBlank(s string) bool { return strings.TrimSpace(s) == "" }

// Update is update_trigger_from_payload: only the fields in p change.
func (s *Service) Update(ctx context.Context, id string, p Patch) (domain.Trigger, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Trigger{}, err
	}
	if err := s.perms.Require(ctx, c, "edit", "trigger", id); err != nil {
		return domain.Trigger{}, err
	}
	cur, err := s.Get(ctx, id)
	if err != nil {
		return domain.Trigger{}, err
	}
	if err := s.validateUpdate(ctx, c, cur, p); err != nil {
		return domain.Trigger{}, err
	}
	next := cur
	if p.AgentID != nil {
		next.AgentID = *p.AgentID
	}
	if p.AgentID != nil || (p.Enabled != nil && *p.Enabled && !cur.IsActive) {
		if err := s.perms.Require(ctx, c, "execute", "agent", next.AgentID); err != nil {
			return domain.Trigger{}, err
		}
	}
	if p.Name != nil {
		next.Name = *p.Name
	}
	if p.Description != nil {
		next.Description = *p.Description
	}
	if p.Conditions != nil {
		next.Conditions = p.Conditions
	}
	if p.TaskParameters != nil {
		next.TaskParameters = domain.DropReserved(p.TaskParameters)
	}
	next.TaskDefinitionID = taskDefinitionAfter(cur, p)
	if p.FailureThreshold != nil {
		next.FailureThreshold = *p.FailureThreshold
	}
	if p.SessionSet || p.Session != nil {
		next.Session = p.Session
	}
	if p.BatchSet || p.Batch != nil {
		next.Batch = p.Batch
	}
	if p.CronExpression != nil {
		next.CronExpression = p.CronExpression
	}
	if p.Timezone != nil {
		next.Timezone = p.Timezone
	}
	if p.Enabled != nil {
		next.IsActive = *p.Enabled
		if next.IsActive {
			next.NeedsNewOwnerAt = nil
		}
	}
	if p.EventFilter != nil {
		if cur.Binding == nil {
			return domain.Trigger{}, domain.ErrNoSubscription
		}
		f, err := domain.ParseEventFilter(p.EventFilter)
		if err != nil {
			return domain.Trigger{}, err
		}
		next.Binding = &domain.Binding{StreamID: cur.Binding.StreamID, Filter: f.Dump(), LastEventAt: cur.Binding.LastEventAt}
	}
	now := s.now()
	next.UpdatedAt = now
	uid, _ := uuid.Parse(id)
	var batches []string
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		if p.Enabled != nil && !*p.Enabled && cur.IsActive {
			if batches, err = s.CloseOpenBatches(ctx, sess, cur, "trigger disabled"); err != nil {
				return err
			}
		}
		ok, err := s.st.Update(ctx, sess, next, now)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrNotFound
		}
		if next.Binding != nil && (p.EventFilter != nil || p.Enabled != nil) {
			if err := s.syncSubscription(ctx, sess, c, uid, *next.Binding, next.IsActive); err != nil {
				return err
			}
		}
		s.audit(ctx, sess, c, "trigger.update", id)
		return nil
	})
	if err != nil {
		return domain.Trigger{}, err
	}
	s.CancelBatches(ctx, id, batches)
	if next.Type == domain.TypeCron && (p.CronExpression != nil || p.Timezone != nil || p.Enabled != nil) {
		s.applySchedule(ctx, next)
	}
	return s.Get(ctx, id)
}

func (s *Service) syncSubscription(ctx context.Context, sess db.Session, c authn.Caller, triggerID uuid.UUID, b domain.Binding, active bool) error {
	streamID, err := uuid.Parse(b.StreamID)
	if err != nil {
		return err
	}
	ok, err := s.st.UpdateSubscription(ctx, sess, triggerID, streamID, b.Filter, subStatus(active))
	if err != nil {
		return err
	}
	if !ok {
		return domain.ErrNoSubscription
	}
	return subscriptionsChanged(ctx, sess, c.UserID, b.StreamID)
}

// Delete removes the trigger, its cron schedule first (a schedule error is logged, not returned).
func (s *Service) Delete(ctx context.Context, id string) error {
	c, err := callerOf(ctx)
	if err != nil {
		return err
	}
	if err := s.perms.Require(ctx, c, "delete", "trigger", id); err != nil {
		return err
	}
	cur, err := s.Get(ctx, id)
	if err != nil {
		return err
	}
	if cur.Type == domain.TypeCron && s.d.Schedules != nil {
		if err := s.d.Schedules.Delete(ctx, "cron-trigger-"+cur.ID); err != nil && !errors.Is(err, durable.ErrNotFound) {
			s.log.ErrorContext(ctx, "could not delete the cron schedule of a trigger", "trigger_id", cur.ID, "error", err)
		}
	}
	u, _ := uuid.Parse(id)
	var batches []string
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		if batches, err = s.CloseOpenBatches(ctx, sess, cur, "trigger deleted"); err != nil {
			return err
		}
		ok, err := s.st.Delete(ctx, sess, u)
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrNotFound
		}
		if cur.Binding != nil {
			if err := subscriptionsChanged(ctx, sess, c.UserID, cur.Binding.StreamID); err != nil {
				return err
			}
		}
		s.audit(ctx, sess, c, "trigger.delete", id)
		return nil
	})
	if err != nil {
		return err
	}
	s.CancelBatches(ctx, id, batches)
	return nil
}

// Enable turns the trigger on, clearing needs_new_owner and its failure count (enable_trigger).
func (s *Service) Enable(ctx context.Context, id string) (domain.Trigger, error) {
	return s.toggle(ctx, id, true)
}

// Disable turns the trigger off and pauses its schedule (disable_trigger).
func (s *Service) Disable(ctx context.Context, id string) (domain.Trigger, error) {
	return s.toggle(ctx, id, false)
}

func (s *Service) toggle(ctx context.Context, id string, active bool) (domain.Trigger, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return domain.Trigger{}, err
	}
	if err := s.perms.Require(ctx, c, "edit", "trigger", id); err != nil {
		return domain.Trigger{}, err
	}
	cur, err := s.Get(ctx, id)
	if err != nil {
		return domain.Trigger{}, err
	}
	if active {
		if err := s.perms.Require(ctx, c, "execute", "agent", cur.AgentID); err != nil {
			return domain.Trigger{}, err
		}
	}
	u, _ := uuid.Parse(id)
	var batches []string
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		if !active {
			if batches, err = s.CloseOpenBatches(ctx, sess, cur, "trigger disabled"); err != nil {
				return err
			}
		}
		ok, err := s.st.SetActive(ctx, sess, u, active, s.now())
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrNotFound
		}
		if cur.Binding == nil {
			return nil
		}
		if _, err := s.st.SetSubscriptionStatus(ctx, sess, u, subStatus(active)); err != nil {
			return err
		}
		return subscriptionsChanged(ctx, sess, c.UserID, cur.Binding.StreamID)
	})
	if err != nil {
		return domain.Trigger{}, err
	}
	s.CancelBatches(ctx, id, batches)
	t, err := s.Get(ctx, id)
	if err != nil {
		return domain.Trigger{}, err
	}
	s.applySchedule(ctx, t)
	return t, nil
}

// applySchedule makes a cron trigger's schedule what its row says; a failure is logged, and the schedule sync repairs it.
func (s *Service) applySchedule(ctx context.Context, t domain.Trigger) {
	if t.Type != domain.TypeCron || t.CronExpression == nil || t.Timezone == nil {
		return
	}
	if s.d.Schedules == nil {
		s.log.ErrorContext(ctx, "no scheduler; cron schedule not applied", "trigger_id", t.ID)
		return
	}
	sched := api.CronTriggerSchedule(t.ID, *t.CronExpression, *t.Timezone, s.d.TriggerQueue, !t.IsActive)
	if err := s.d.Schedules.Ensure(ctx, sched); err != nil {
		s.log.ErrorContext(ctx, "could not apply the cron schedule of a trigger; the schedule sync repairs it", "trigger_id", t.ID, "error", err)
	}
}

// CountByTaskDefinition implements api.Triggers.
func (s *Service) CountByTaskDefinition(ctx context.Context, ws scope.Workspace, definitionID string) (int64, error) {
	u, err := uuid.Parse(definitionID)
	if err != nil {
		return 0, nil
	}
	var n int64
	err = s.read(ctx, ws, func(sess db.Session) error {
		n, err = s.st.CountByTaskDefinition(ctx, sess, u)
		return err
	})
	return n, err
}

// ListTriggers implements api.Triggers.
func (s *Service) ListTriggers(ctx context.Context, ws scope.Workspace, agentID *string) ([]api.TriggerSummary, error) {
	var out []api.TriggerSummary
	err := s.read(ctx, ws, func(sess db.Session) error {
		ts, err := s.st.List(ctx, sess, store.Filter{AgentID: agentID, Limit: 1000})
		if err != nil {
			return err
		}
		for _, t := range ts {
			sum := api.TriggerSummary{ID: t.ID, Name: t.Name, AgentID: t.AgentID, TriggerType: t.Type,
				IsActive: t.IsActive, TaskDefinitionID: t.TaskDefinitionID, CronExpression: t.CronExpression}
			if id, err := uuid.Parse(t.ID); err == nil {
				b, err := s.st.Binding(ctx, sess, id)
				if err != nil {
					return err
				}
				if b != nil {
					sum.StreamID = &b.StreamID
				}
			}
			out = append(out, sum)
		}
		return nil
	})
	return out, err
}
