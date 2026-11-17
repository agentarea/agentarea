package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

//go:generate sqlc generate

// ErrTaskNotFound: the task is not in the session's workspace.
var ErrTaskNotFound = errors.New("task not found in workspace")

// Runs reads and writes a run's record (tasks, task_conversation_entries,
// task_events, cost_entries) inside the session's workspace.
type Runs struct{}

// TaskRef is what a run's writes copy from its task row.
type TaskRef struct {
	ID            string
	CorrelationID string
	CausationID   string
	Status        string
}

// TaskOrigin is what a delegated task inherits from its parent.
type TaskOrigin struct {
	ID             string
	AgentID        string
	CorrelationID  string
	SourceIdentity string
}

// NewTask is a task row a run creates (a delegation child).
type NewTask struct {
	ID             string
	AgentID        string
	Description    string
	Parameters     map[string]any
	Status         string
	ExecutionID    string
	Metadata       map[string]any
	CreatedBy      string
	OriginType     string
	OriginID       string
	CorrelationID  string
	CausationID    string
	ParentTaskID   string
	SourceIdentity string
}

func text(s string) pgtype.Text {
	if s == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: s, Valid: true}
}

func textPtr(p *string) pgtype.Text {
	if p == nil {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func nullUUID(s string) (uuid.NullUUID, error) {
	if s == "" {
		return uuid.NullUUID{}, nil
	}
	u, err := uuid.Parse(s)
	if err != nil {
		return uuid.NullUUID{}, err
	}
	return uuid.NullUUID{UUID: u, Valid: true}, nil
}

func naive(t time.Time) pgtype.Timestamp {
	return pgtype.Timestamp{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

func tstz(t time.Time) pgtype.Timestamptz {
	return pgtype.Timestamptz{Time: t.UTC().Truncate(time.Microsecond), Valid: true}
}

func jsonText(v any) (pgtype.Text, error) {
	if v == nil {
		return pgtype.Text{}, nil
	}
	b, err := json.Marshal(v)
	if err != nil {
		return pgtype.Text{}, err
	}
	return pgtype.Text{String: string(b), Valid: true}, nil
}

func parseUUID(field, s string) (uuid.UUID, error) {
	u, err := uuid.Parse(s)
	if err != nil {
		return uuid.UUID{}, fmt.Errorf("%s %q: %w", field, s, err)
	}
	return u, nil
}

// Task is the task row's ids and status; ErrTaskNotFound when the workspace has none.
func (Runs) Task(ctx context.Context, s db.Session, taskID string) (TaskRef, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return TaskRef{}, err
	}
	row, err := New(s.Q()).TaskForLog(ctx, TaskForLogParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return TaskRef{}, fmt.Errorf("task %s: %w", taskID, ErrTaskNotFound)
	}
	if err != nil {
		return TaskRef{}, err
	}
	return TaskRef{ID: row.ID.String(), CorrelationID: row.CorrelationID.String, CausationID: row.CausationID.String, Status: row.Status}, nil
}

// SetOutcome writes a run's status, result, error and metadata patch; false when the task is gone.
func (Runs) SetOutcome(ctx context.Context, s db.Session, taskID string, o domain.Outcome, now time.Time) (bool, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return false, err
	}
	p := SetTaskOutcomeParams{Status: o.Status, Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID(), SetError: o.SetError, Error: textPtr(o.Error)}
	if o.Result != nil {
		p.SetResult = true
		p.Result = text(domain.PyDumps(domain.Storable(o.Result)))
	}
	if o.MetadataPatch != nil {
		patch, err := json.Marshal(domain.Storable(o.MetadataPatch))
		if err != nil {
			return false, err
		}
		p.PatchMetadata, p.MetadataPatch = true, string(patch)
	} else {
		p.MetadataPatch = "{}"
	}
	n, err := New(s.Q()).SetTaskOutcome(ctx, p)
	return n > 0, err
}

// MergeMetadata merges patch into the task's metadata, leaving other keys alone.
func (Runs) MergeMetadata(ctx context.Context, s db.Session, taskID string, patch map[string]any, now time.Time) (bool, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return false, err
	}
	b, err := json.Marshal(domain.Storable(patch))
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).MergeTaskMetadata(ctx, MergeTaskMetadataParams{Patch: string(b), Now: naive(now), ID: id, WorkspaceID: s.Workspace().ID()})
	return n > 0, err
}

// Origin is what a delegated task copies from its parent; ErrTaskNotFound when gone.
func (Runs) Origin(ctx context.Context, s db.Session, taskID string) (TaskOrigin, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return TaskOrigin{}, err
	}
	row, err := New(s.Q()).TaskProvenance(ctx, TaskProvenanceParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if errors.Is(err, pgx.ErrNoRows) {
		return TaskOrigin{}, fmt.Errorf("task %s: %w", taskID, ErrTaskNotFound)
	}
	if err != nil {
		return TaskOrigin{}, err
	}
	return TaskOrigin{ID: row.ID.String(), AgentID: row.AgentID.String(), CorrelationID: row.CorrelationID.String, SourceIdentity: row.SourceIdentity.String}, nil
}

// CreateTask inserts a task row; a task no event started begins its own correlation chain.
func (Runs) CreateTask(ctx context.Context, s db.Session, t NewTask, now time.Time) error {
	id, err := parseUUID("task id", t.ID)
	if err != nil {
		return err
	}
	agentID, err := parseUUID("agent id", t.AgentID)
	if err != nil {
		return err
	}
	parent, err := nullUUID(t.ParentTaskID)
	if err != nil {
		return err
	}
	params, err := json.Marshal(domain.Storable(t.Parameters))
	if err != nil {
		return err
	}
	meta, err := json.Marshal(domain.Storable(t.Metadata))
	if err != nil {
		return err
	}
	correlation := t.CorrelationID
	if correlation == "" {
		correlation = t.ID
	}
	return New(s.Q()).InsertTask(ctx, InsertTaskParams{
		ID: id, AgentID: agentID, Description: t.Description, Parameters: string(params), Status: t.Status,
		ExecutionID: text(t.ExecutionID), TaskMetadata: string(meta), WorkspaceID: s.Workspace().ID(),
		CreatedBy: t.CreatedBy, Now: naive(now), OriginType: text(t.OriginType), OriginID: text(t.OriginID),
		CorrelationID: text(correlation), CausationID: text(t.CausationID), ParentTaskID: parent,
		SourceIdentity: text(t.SourceIdentity),
	})
}

// InsertEntry writes one log row once per (task, event id); bodies are already offloaded.
func (Runs) InsertEntry(ctx context.Context, s db.Session, task TaskRef, e domain.Entry, createdBy string) error {
	taskID, err := parseUUID("task id", task.ID)
	if err != nil {
		return err
	}
	eventID, err := parseUUID("event id", e.EventID)
	if err != nil {
		return fmt.Errorf("log row %d of task %s: %w", e.Seq, task.ID, err)
	}
	p := InsertEntryParams{
		ID: uuid.New(), TaskID: taskID, Seq: int32(e.Seq), EventID: eventID, Kind: e.Kind,
		Role: domain.StorableText(e.Role), Content: domain.StorableText(e.Content),
		ToolCallID: text(domain.StorableText(e.ToolCallID)), Name: text(domain.StorableText(e.Name)),
		ExecutionID: text(e.ExecutionID), CorrelationID: text(task.CorrelationID), CausationID: text(task.CausationID),
		BodyRef: text(e.BodyRef), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy,
	}
	if e.ToolCalls != nil {
		if p.ToolCalls, err = jsonText(domain.Storable(domain.ToolCallsJSON(e.ToolCalls))); err != nil {
			return err
		}
	}
	if e.Attachments != nil {
		if p.Attachments, err = jsonText(e.Attachments); err != nil {
			return err
		}
	}
	if e.Meta != nil {
		if p.Meta, err = jsonText(domain.StorableMap(e.Meta)); err != nil {
			return err
		}
	}
	if e.Iteration != nil {
		p.Iteration = pgtype.Int4{Int32: int32(*e.Iteration), Valid: true}
	}
	if e.OccurredAt != nil {
		p.CreatedAt = tstz(*e.OccurredAt)
	}
	return New(s.Q()).InsertEntry(ctx, p)
}

func entryOf(r WindowEntriesRow) (domain.Entry, error) {
	e := domain.Entry{
		Seq: int64(r.Seq), EventID: r.EventID.String(), Kind: r.Kind, Role: r.Role, Content: r.Content,
		ToolCallID: r.ToolCallID.String, Name: r.Name.String, ExecutionID: r.ExecutionID.String, BodyRef: r.BodyRef.String,
	}
	calls, err := domain.ParseToolCalls([]byte(r.ToolCalls))
	if err != nil {
		return e, fmt.Errorf("tool calls of row %d: %w", r.Seq, err)
	}
	e.ToolCalls = calls
	if r.Attachments != "" && r.Attachments != "null" {
		if err := json.Unmarshal([]byte(r.Attachments), &e.Attachments); err != nil {
			return e, fmt.Errorf("attachments of row %d: %w", r.Seq, err)
		}
	}
	if r.Meta != "" && r.Meta != "null" {
		if err := json.Unmarshal([]byte(r.Meta), &e.Meta); err != nil {
			return e, fmt.Errorf("meta of row %d: %w", r.Seq, err)
		}
	}
	if r.Iteration.Valid {
		it := int(r.Iteration.Int32)
		e.Iteration = &it
	}
	if r.CreatedAt.Valid {
		t := r.CreatedAt.Time
		e.OccurredAt = &t
	}
	return e, nil
}

// Window is the rows the model's window is built from, before endSeq, body references unresolved.
func (Runs) Window(ctx context.Context, s db.Session, taskID string, endSeq int64) ([]domain.Entry, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return nil, err
	}
	rows, err := New(s.Q()).WindowEntries(ctx, WindowEntriesParams{TaskID: id, WorkspaceID: s.Workspace().ID(), EndSeq: int32(endSeq)})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Entry, 0, len(rows))
	for _, r := range rows {
		e, err := entryOf(r)
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, nil
}

// LatestFeed is the newest feed rows of the given types (all when none), newest first.
func (Runs) LatestFeed(ctx context.Context, s db.Session, taskID string, types []string, limit int) ([]domain.Entry, error) {
	id, err := parseUUID("task id", taskID)
	if err != nil {
		return nil, err
	}
	if types == nil {
		types = []string{}
	}
	rows, err := New(s.Q()).LatestFeedEntries(ctx, LatestFeedEntriesParams{TaskID: id, WorkspaceID: s.Workspace().ID(), EventTypes: types, MaxRows: int32(limit)})
	if err != nil {
		return nil, err
	}
	out := make([]domain.Entry, 0, len(rows))
	for _, r := range rows {
		e, err := entryOf(WindowEntriesRow(r))
		if err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, nil
}

// InsertTaskEvent stores a workflow event in task_events once under its id.
func (Runs) InsertTaskEvent(ctx context.Context, s db.Session, taskID string, e domain.StoredEvent, createdBy string, now time.Time) error {
	id, err := parseUUID("event id", e.ID)
	if err != nil {
		return err
	}
	task, err := parseUUID("task id", taskID)
	if err != nil {
		return err
	}
	data, err := json.Marshal(domain.StorableMap(e.Data))
	if err != nil {
		return err
	}
	meta, err := json.Marshal(map[string]any{"source": "workflow", "created_at": now.UTC().Format("2006-01-02T15:04:05.999999+00:00")})
	if err != nil {
		return err
	}
	return New(s.Q()).InsertTaskEvent(ctx, InsertTaskEventParams{
		ID: id, TaskID: task, EventType: e.Type, OccurredAt: tstz(e.Timestamp), Data: string(data),
		EventMetadata: string(meta), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy,
	})
}

// InsertCostLine stores a ledger line once per (event, category); true when it was new.
func (Runs) InsertCostLine(ctx context.Context, s db.Session, l domain.CostLine, createdBy string, chain TaskRef) (bool, error) {
	eventID, err := parseUUID("event id", l.EventID)
	if err != nil {
		return false, err
	}
	taskID, err := nullUUID(l.TaskID)
	if err != nil {
		return false, err
	}
	agentID, err := nullUUID(l.AgentID)
	if err != nil {
		return false, err
	}
	clientID, err := nullUUID(l.ClientID)
	if err != nil {
		return false, err
	}
	evidence := l.Evidence
	if evidence == nil {
		evidence = map[string]any{}
	}
	ev, err := json.Marshal(domain.StorableMap(evidence))
	if err != nil {
		return false, err
	}
	n, err := New(s.Q()).InsertCostLine(ctx, InsertCostLineParams{
		ID: uuid.New(), WorkspaceID: s.Workspace().ID(), CreatedBy: createdBy, EventID: eventID, Category: l.Category,
		TaskID: taskID, AgentID: agentID, SubjectType: l.SubjectType, SubjectID: textPtr(l.SubjectID),
		SubjectName: textPtr(l.SubjectName), CallRef: textPtr(l.CallRef), Amount: l.Amount, Currency: text(l.Currency),
		ProviderCostUsd: textPtr(l.ProviderCostUSD), Source: l.Source, Evidence: string(ev), OccurredAt: tstz(l.OccurredAt),
		Payer: l.Payer, VendorCost: textPtr(l.VendorCost), VendorCurrency: textPtr(l.VendorCurrency), Estimate: l.Estimate,
		CorrelationID: text(chain.CorrelationID), CausationID: text(chain.CausationID),
		Quantity: textPtr(l.Quantity), Unit: textPtr(l.Unit), ClientID: clientID,
	})
	return n > 0, err
}

// SpendScope narrows a ledger sum; empty fields do not narrow.
type SpendScope struct {
	AgentID      string
	TaskID       string
	Category     string
	ConnectionID string
	Tool         string
	ClientID     string
}

// SumSpendSince is the total of the workspace's current lines in currency since a UTC instant.
func (Runs) SumSpendSince(ctx context.Context, s db.Session, since time.Time, currency string, scope SpendScope) (string, error) {
	agentID, err := nullUUID(scope.AgentID)
	if err != nil {
		return "", err
	}
	taskID, err := nullUUID(scope.TaskID)
	if err != nil {
		return "", err
	}
	clientID, err := nullUUID(scope.ClientID)
	if err != nil {
		return "", err
	}
	return New(s.Q()).SumSpendSince(ctx, SumSpendSinceParams{
		WorkspaceID: s.Workspace().ID(), Since: tstz(since), Currency: text(currency),
		AgentID: agentID, TaskID: taskID, Category: text(scope.Category),
		ConnectionID: text(scope.ConnectionID), Tool: text(scope.Tool), ClientID: clientID,
	})
}

// Refused reports a write the database refuses for its data (classes 22 and
// 23: bad value, constraint); retrying would refuse it again.
func Refused(err error) (string, bool) {
	var pg *pgconn.PgError
	if errors.As(err, &pg) && len(pg.Code) >= 2 && (pg.Code[:2] == "22" || pg.Code[:2] == "23") {
		return pg.Message, true
	}
	return "", false
}
