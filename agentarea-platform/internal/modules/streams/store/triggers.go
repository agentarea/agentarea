package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

//go:generate sqlc generate

// Triggers reads and writes triggers, their stream subscriptions and their
// execution rows inside the session's workspace.
type Triggers struct{}

// Filter selects triggers of a workspace (ListTriggers).
type Filter struct {
	AgentID     *string
	TriggerType *string
	ActiveOnly  bool
	Limit       int32
}

// Execution is one trigger_executions row to record.
type Execution struct {
	Status        string
	ExecutionTime time.Duration
	TaskID        *string
	ErrorMessage  *string
	TriggerData   map[string]any
	FiredBy       *string
}

// Cron is a cron trigger row as the schedule sync reads it.
type Cron struct {
	ID          string
	WorkspaceID string
	Expression  string
	Timezone    string
	Active      bool
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

func nullUUID(p *string) (uuid.NullUUID, error) {
	if p == nil {
		return uuid.NullUUID{}, nil
	}
	u, err := uuid.Parse(*p)
	if err != nil {
		return uuid.NullUUID{}, err
	}
	return uuid.NullUUID{UUID: u, Valid: true}, nil
}

func fromNullUUID(u uuid.NullUUID) *string {
	if !u.Valid {
		return nil
	}
	s := u.UUID.String()
	return &s
}

// naive is a timestamp without time zone holding t's UTC wall clock (triggers store naive UTC).
func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

func fromNaive(t pgtype.Timestamp) time.Time { return t.Time.UTC() }

func fromNaivePtr(t pgtype.Timestamp) *time.Time {
	if !t.Valid {
		return nil
	}
	v := t.Time.UTC()
	return &v
}

func nullNaive(p *time.Time) pgtype.Timestamp {
	if p == nil {
		return pgtype.Timestamp{}
	}
	return naive(*p)
}

func marshal(v any) ([]byte, error) {
	if v == nil {
		return []byte("null"), nil
	}
	return json.Marshal(v)
}

func unmarshalMap(b []byte) (map[string]any, error) {
	var m map[string]any
	if len(b) == 0 {
		return map[string]any{}, nil
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return nil, err
	}
	if m == nil {
		m = map[string]any{}
	}
	return m, nil
}

func unmarshalPtr[T any](b []byte) (*T, error) {
	if len(b) == 0 || string(b) == "null" {
		return nil, nil
	}
	var v T
	if err := json.Unmarshal(b, &v); err != nil {
		return nil, err
	}
	return &v, nil
}

func toTrigger(r Trigger) (domain.Trigger, error) {
	params, err := unmarshalMap(r.TaskParameters)
	if err != nil {
		return domain.Trigger{}, err
	}
	conds, err := unmarshalMap(r.Conditions)
	if err != nil {
		return domain.Trigger{}, err
	}
	sess, err := unmarshalPtr[domain.Session](r.Session)
	if err != nil {
		return domain.Trigger{}, err
	}
	batch, err := unmarshalPtr[domain.Batch](r.Batch)
	if err != nil {
		return domain.Trigger{}, err
	}
	return domain.Trigger{
		ID: r.ID.String(), WorkspaceID: r.WorkspaceID, Name: r.Name, Description: r.Description,
		AgentID: r.AgentID.String(), TaskDefinitionID: fromNullUUID(r.TaskDefinitionID), Type: r.TriggerType,
		IsActive: r.IsActive, TaskParameters: params, Conditions: conds,
		FailureThreshold: int(r.FailureThreshold), Consecutive: int(r.ConsecutiveFailures),
		LastExecutionAt: fromNaivePtr(r.LastExecutionAt), CronExpression: fromText(r.CronExpression),
		Timezone: fromText(r.Timezone), NeedsNewOwnerAt: fromNaivePtr(r.NeedsNewOwnerAt),
		Session: sess, Batch: batch, CreatedBy: r.CreatedBy,
		CreatedAt: fromNaive(r.CreatedAt), UpdatedAt: fromNaive(r.UpdatedAt),
	}, nil
}

// Insert writes a trigger row with the given id.
func (Triggers) Insert(ctx context.Context, s db.Session, id uuid.UUID, t domain.Trigger, now time.Time) error {
	td, err := nullUUID(t.TaskDefinitionID)
	if err != nil {
		return err
	}
	agent, err := uuid.Parse(t.AgentID)
	if err != nil {
		return err
	}
	params, err := marshal(t.TaskParameters)
	if err != nil {
		return err
	}
	conds, err := marshal(t.Conditions)
	if err != nil {
		return err
	}
	sess, err := marshal(t.Session)
	if err != nil {
		return err
	}
	batch, err := marshal(t.Batch)
	if err != nil {
		return err
	}
	_, err = New(s.Q()).InsertTrigger(ctx, InsertTriggerParams{
		ID: id, Name: t.Name, Description: t.Description, AgentID: agent, TriggerType: t.Type,
		IsActive: t.IsActive, TaskParameters: params, Conditions: conds, FailureThreshold: int32(t.FailureThreshold),
		CronExpression: text(t.CronExpression), Timezone: text(t.Timezone), WorkspaceID: s.Workspace().ID(),
		CreatedBy: t.CreatedBy, Now: naive(now), Session: sess, Batch: batch, TaskDefinitionID: td,
	})
	return err
}

// Get returns the trigger in the session's workspace, false when none.
func (Triggers) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Trigger, bool, error) {
	r, err := New(s.Q()).GetTrigger(ctx, GetTriggerParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Trigger{}, false, nil
	}
	if err != nil {
		return domain.Trigger{}, false, err
	}
	t, err := toTrigger(r)
	return t, err == nil, err
}

// GetAnyWorkspace reads a trigger by id across workspaces (the runs reconciler's reads).
func (Triggers) GetAnyWorkspace(ctx context.Context, q db.Querier, id uuid.UUID) (domain.Trigger, bool, error) {
	r, err := New(q).GetTriggerAnyWorkspace(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Trigger{}, false, nil
	}
	if err != nil {
		return domain.Trigger{}, false, err
	}
	t, err := toTrigger(r)
	return t, err == nil, err
}

// List returns the workspace's triggers, oldest first.
func (Triggers) List(ctx context.Context, s db.Session, f Filter) ([]domain.Trigger, error) {
	var agent uuid.NullUUID
	if f.AgentID != nil {
		a, err := uuid.Parse(*f.AgentID)
		if err != nil {
			return nil, nil
		}
		agent = uuid.NullUUID{UUID: a, Valid: true}
	}
	rows, err := New(s.Q()).ListTriggers(ctx, ListTriggersParams{
		WorkspaceID: s.Workspace().ID(), AgentID: agent, TriggerType: text(f.TriggerType),
		ActiveOnly: f.ActiveOnly, Lim: f.Limit,
	})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Trigger, 0, len(rows))
	for _, r := range rows {
		t, err := toTrigger(r)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, nil
}

// CountByTaskDefinition counts the triggers that ask a saved task.
func (Triggers) CountByTaskDefinition(ctx context.Context, s db.Session, definitionID uuid.UUID) (int64, error) {
	return New(s.Q()).CountTriggersByTaskDefinition(ctx, CountTriggersByTaskDefinitionParams{
		WorkspaceID: s.Workspace().ID(), TaskDefinitionID: uuid.NullUUID{UUID: definitionID, Valid: true},
	})
}

// Update writes the mutable columns of t; false when the row is gone.
func (Triggers) Update(ctx context.Context, s db.Session, t domain.Trigger, now time.Time) (bool, error) {
	id, err := uuid.Parse(t.ID)
	if err != nil {
		return false, err
	}
	agent, err := uuid.Parse(t.AgentID)
	if err != nil {
		return false, err
	}
	td, err := nullUUID(t.TaskDefinitionID)
	if err != nil {
		return false, err
	}
	params, err := marshal(t.TaskParameters)
	if err != nil {
		return false, err
	}
	conds, err := marshal(t.Conditions)
	if err != nil {
		return false, err
	}
	sess, err := marshal(t.Session)
	if err != nil {
		return false, err
	}
	batch, err := marshal(t.Batch)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).UpdateTriggerRow(ctx, UpdateTriggerRowParams{
		Name: t.Name, Description: t.Description, AgentID: agent, IsActive: t.IsActive,
		TaskParameters: params, Conditions: conds, FailureThreshold: int32(t.FailureThreshold),
		CronExpression: text(t.CronExpression), Timezone: text(t.Timezone), Session: sess, Batch: batch,
		TaskDefinitionID: td, NeedsNewOwnerAt: nullNaive(t.NeedsNewOwnerAt), Now: naive(now),
		WorkspaceID: s.Workspace().ID(), ID: id,
	})
	return n == 1, err
}

// Delete removes the trigger; its executions and subscription go with it by foreign key.
func (Triggers) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteTrigger(ctx, DeleteTriggerParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n == 1, err
}

// Binding is the trigger's stream subscription, nil when it has none.
func (Triggers) Binding(ctx context.Context, s db.Session, id uuid.UUID) (*domain.Binding, error) {
	r, err := New(s.Q()).GetTriggerBinding(ctx, uuid.NullUUID{UUID: id, Valid: true})
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	f, err := unmarshalMap(r.Filter)
	if err != nil {
		return nil, err
	}
	return &domain.Binding{StreamID: r.StreamID.String(), Filter: f, LastEventAt: fromNaivePtr(r.LastEventAt)}, nil
}

// InsertSubscription writes the trigger's stream subscription.
func (Triggers) InsertSubscription(ctx context.Context, s db.Session, subID, streamID, triggerID uuid.UUID, filter map[string]any, status, createdBy string, now time.Time) error {
	f, err := marshal(filter)
	if err != nil {
		return err
	}
	return New(s.Q()).InsertTriggerSubscription(ctx, InsertTriggerSubscriptionParams{
		ID: subID, StreamID: streamID, WorkspaceID: s.Workspace().ID(), TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true},
		Filter: f, Status: status, StartedAt: pgtype.Timestamptz{Time: now.UTC(), Valid: true}, CreatedAt: naive(now), CreatedBy: createdBy,
	})
}

// UpdateSubscription sets the stream and filter of the trigger's subscription; false when it has none.
func (Triggers) UpdateSubscription(ctx context.Context, s db.Session, triggerID, streamID uuid.UUID, filter map[string]any, status string) (bool, error) {
	f, err := marshal(filter)
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).UpdateTriggerSubscriptionFilter(ctx, UpdateTriggerSubscriptionFilterParams{
		TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, Filter: f, StreamID: streamID, Status: status,
	})
	return n == 1, err
}

// SetSubscriptionStatus sets the status of the trigger's subscription.
func (Triggers) SetSubscriptionStatus(ctx context.Context, s db.Session, triggerID uuid.UUID, status string) (bool, error) {
	n, err := New(s.Q()).SetTriggerSubscriptionStatus(ctx, SetTriggerSubscriptionStatusParams{
		TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, Status: status,
	})
	return n == 1, err
}

// StreamExists reports whether the workspace has the stream.
func (Triggers) StreamExists(ctx context.Context, s db.Session, streamID uuid.UUID) (bool, error) {
	return New(s.Q()).StreamExists(ctx, StreamExistsParams{WorkspaceID: s.Workspace().ID(), ID: streamID})
}

// Crons lists every workspace's cron triggers.
func (Triggers) Crons(ctx context.Context, q db.Querier) ([]Cron, error) {
	rows, err := New(q).ListCronTriggers(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]Cron, 0, len(rows))
	for _, r := range rows {
		out = append(out, Cron{ID: r.ID.String(), WorkspaceID: r.WorkspaceID, Expression: r.CronExpression.String,
			Timezone: r.Timezone.String, Active: r.IsActive})
	}
	return out, nil
}

// RecordExecution inserts the trigger's execution row and returns its id and time.
func (Triggers) RecordExecution(ctx context.Context, s db.Session, triggerID uuid.UUID, e Execution, now time.Time) (uuid.UUID, time.Time, error) {
	task, err := nullUUID(e.TaskID)
	if err != nil {
		return uuid.Nil, time.Time{}, err
	}
	data, err := marshal(e.TriggerData)
	if err != nil {
		return uuid.Nil, time.Time{}, err
	}
	id := uuid.New()
	r, err := New(s.Q()).InsertTriggerExecution(ctx, InsertTriggerExecutionParams{
		ID: id, TriggerID: triggerID, ExecutedAt: naive(now), Status: e.Status, TaskID: task,
		ExecutionTimeMs: int32(e.ExecutionTime / time.Millisecond), ErrorMessage: text(e.ErrorMessage),
		TriggerData: data, FiredBy: text(e.FiredBy),
	})
	if err != nil {
		return uuid.Nil, time.Time{}, err
	}
	return r.ID, fromNaive(r.ExecutedAt), nil
}

// MarkExecuted sets last_execution_at and the failure count (reset on success).
func (Triggers) MarkExecuted(ctx context.Context, s db.Session, triggerID uuid.UUID, at time.Time, reset bool) error {
	_, err := New(s.Q()).MarkTriggerExecuted(ctx, MarkTriggerExecutedParams{ExecutedAt: naive(at), Reset: reset, ID: triggerID})
	return err
}

// Executions lists the trigger's execution rows, newest first.
func (Triggers) Executions(ctx context.Context, s db.Session, triggerID uuid.UUID, limit int32) ([]domain.Execution, error) {
	rows, err := New(s.Q()).ListTriggerExecutions(ctx, ListTriggerExecutionsParams{
		TriggerID: uuid.NullUUID{UUID: triggerID, Valid: true}, WorkspaceID: s.Workspace().ID(), Lim: limit,
	})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Execution, 0, len(rows))
	for _, r := range rows {
		data, err := unmarshalMap(r.TriggerData)
		if err != nil {
			return nil, err
		}
		out = append(out, domain.Execution{
			ID: r.ID.String(), TriggerID: triggerID.String(), ExecutedAt: fromNaive(r.ExecutedAt), Status: r.Status,
			TaskID: fromNullUUID(r.TaskID), ExecutionTimeMs: int(r.ExecutionTimeMs), ErrorMessage: fromText(r.ErrorMessage),
			TriggerData: data, WorkflowID: fromText(r.WorkflowID), RunID: fromText(r.RunID), FiredBy: fromText(r.FiredBy),
		})
	}
	return out, nil
}

// SetActive turns the trigger on or off; on clears needs_new_owner and the failure count
// (enable_trigger, disable_trigger). False when the row is gone.
func (Triggers) SetActive(ctx context.Context, s db.Session, id uuid.UUID, active bool, now time.Time) (bool, error) {
	n, err := New(s.Q()).SetTriggerActive(ctx, SetTriggerActiveParams{
		IsActive: active, Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id,
	})
	return n == 1, err
}
