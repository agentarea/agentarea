package store

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/domain"
)

func makeSurfaceTask(t *testing.T, s db.Session, agentID uuid.UUID, description, status string) uuid.UUID {
	t.Helper()
	id := uuid.New()
	if err := (Runs{}).CreateTask(context.Background(), s, NewTask{
		ID: id.String(), AgentID: agentID.String(), Description: description, Status: status, CreatedBy: "user-1",
	}, time.Now()); err != nil {
		t.Fatal(err)
	}
	return id
}

func TestSurfaceTaskPageFiltersAndEscapesSearch(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	agent, named := uuid.New(), uuid.New()
	pct := makeSurfaceTask(t, s, agent, "grew 50% today", "running")
	makeSurfaceTask(t, s, agent, "grew 50 today", "completed")
	byAgent := makeSurfaceTask(t, s, named, "other", "failed")
	makeSurfaceTask(t, other, agent, "grew 50% today", "running")
	q := New(s.Q())
	page := func(p SurfaceTaskPageParams) []uuid.UUID {
		t.Helper()
		p.WorkspaceID, p.MaxRows = s.Workspace().ID(), 10
		if p.Statuses == nil {
			p.Statuses = []string{}
		}
		if p.SearchAgentIds == nil {
			p.SearchAgentIds = []uuid.UUID{}
		}
		rows, err := q.SurfaceTaskPage(ctx, p)
		if err != nil {
			t.Fatal(err)
		}
		ids := make([]uuid.UUID, len(rows))
		for i, r := range rows {
			ids[i] = r.ID
		}
		return ids
	}
	if got := page(SurfaceTaskPageParams{}); len(got) != 3 {
		t.Fatalf("all: %v", got)
	}
	if got := page(SurfaceTaskPageParams{Search: pgtype.Text{String: "0/%", Valid: true}}); len(got) != 1 || got[0] != pct {
		t.Fatalf("escaped %% matches literally: %v", got)
	}
	got := page(SurfaceTaskPageParams{Search: pgtype.Text{String: "zzz", Valid: true}, SearchAgentIds: []uuid.UUID{named}})
	if len(got) != 1 || got[0] != byAgent {
		t.Fatalf("agent-name match: %v", got)
	}
	if got := page(SurfaceTaskPageParams{Statuses: []string{"running", "failed"}}); len(got) != 2 {
		t.Fatalf("statuses: %v", got)
	}
}

func TestSurfaceCancelScheduledKeepsAnEarlierCancellationTime(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	q := New(s.Q())
	id := makeSurfaceTask(t, s, uuid.New(), "d", "scheduled")
	first := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	for _, now := range []time.Time{first, first.Add(time.Hour)} {
		if _, err := q.SurfaceCancelScheduled(ctx, SurfaceCancelScheduledParams{Now: pgtype.Timestamp{Time: now, Valid: true}, ID: id, WorkspaceID: s.Workspace().ID()}); err != nil {
			t.Fatal(err)
		}
	}
	row, err := q.SurfaceTask(ctx, SurfaceTaskParams{ID: id, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		t.Fatal(err)
	}
	if row.Status != "cancelled" || !row.CompletedAt.Time.Equal(first) {
		t.Fatalf("status %s completed_at %v", row.Status, row.CompletedAt.Time)
	}
}

func TestSurfaceInboxListsWhatWaitsOnAPerson(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	q := New(s.Q())
	agent := uuid.New()
	waiting := makeSurfaceTask(t, s, agent, "w", "waiting_for_input")
	blocked := makeSurfaceTask(t, s, agent, "b", "blocked")
	for _, status := range []string{"running", "completed", "failed"} {
		makeSurfaceTask(t, s, agent, status, status)
	}
	if err := (Runs{}).CreateTask(ctx, s, NewTask{
		ID: uuid.NewString(), AgentID: agent.String(), Description: "child", Status: "blocked", CreatedBy: "user-1",
		Metadata: map[string]any{"created_via": "agent_delegation"},
	}, time.Now()); err != nil {
		t.Fatal(err)
	}
	statuses := runsapi.InboxStatuses()
	rows, err := q.SurfaceInboxPage(ctx, SurfaceInboxPageParams{WorkspaceID: s.Workspace().ID(), Statuses: statuses, MaxRows: 10})
	if err != nil {
		t.Fatal(err)
	}
	n, err := q.SurfaceInboxCount(ctx, SurfaceInboxCountParams{WorkspaceID: s.Workspace().ID(), Statuses: statuses})
	if err != nil {
		t.Fatal(err)
	}
	got := map[uuid.UUID]bool{}
	for _, r := range rows {
		got[r.ID] = true
	}
	if len(rows) != 2 || !got[waiting] || !got[blocked] || n != 2 {
		t.Fatalf("inbox %v total %d", rows, n)
	}
}

func TestSurfaceFeedReadsEventsAndUserMessages(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var r Runs
	task := newTask(t, s)
	at := time.Now().UTC()
	entries := []domain.Entry{
		{EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "user", Content: "hi", OccurredAt: &at},
		{EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "assistant", Content: "x", OccurredAt: &at,
			ToolCalls: []domain.ToolCall{{ID: "c1", Name: "shell", Arguments: `{"cmd":"ls"}`}}},
		{EventID: uuid.NewString(), Kind: domain.KindEvent, Name: domain.EventToolCall, Meta: map[string]any{"tool_call_id": "c1"}, OccurredAt: &at},
		{EventID: uuid.NewString(), Kind: domain.KindMessage, Role: "tool", ToolCallID: "c1", Content: "out", OccurredAt: &at},
	}
	for i, e := range entries {
		e.Seq = int64(i)
		if err := r.InsertEntry(ctx, s, task, e, "user-1"); err != nil {
			t.Fatal(err)
		}
	}
	q := New(s.Q())
	id := uuid.MustParse(task.ID)
	rows, err := q.SurfaceFeedAfter(ctx, SurfaceFeedAfterParams{TaskID: id, WorkspaceID: s.Workspace().ID(), AfterSeq: -1, MaxRows: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || rows[0].Role != "user" || rows[1].Name.String != domain.EventToolCall {
		t.Fatalf("feed %+v", rows)
	}
	n, err := q.SurfaceFeedCount(ctx, SurfaceFeedCountParams{TaskID: id, WorkspaceID: s.Workspace().ID(), EventType: pgtype.Text{String: domain.EventMessageReceived, Valid: true}})
	if err != nil || n != 1 {
		t.Fatalf("message.received count %d %v", n, err)
	}
	bodies, err := q.SurfaceFeedBodies(ctx, SurfaceFeedBodiesParams{TaskID: id, WorkspaceID: s.Workspace().ID(), CallIds: []string{"c1"}})
	if err != nil || len(bodies) != 2 {
		t.Fatalf("bodies %+v %v", bodies, err)
	}
	if _, err := q.SurfaceFeedAt(ctx, SurfaceFeedAtParams{TaskID: id, WorkspaceID: s.Workspace().ID(), Seq: 1}); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("an assistant row is not a feed row: %v", err)
	}
}

func insertApproval(t *testing.T, pool *pgxpool.Pool, s db.Session, status string, expires time.Time) uuid.UUID {
	t.Helper()
	id := uuid.New()
	_, err := pool.Exec(context.Background(), `INSERT INTO tool_call_approvals
		(id, workspace_id, created_by, connector, tool, policy_name, arguments, arguments_hash, status, reason, approvers, expires_at, created_at, updated_at)
		VALUES ($1, $2, 'user-1', 'c', 't', 'p', '{"a": 1}', 'h', $3, 'r', '["user-2"]', $4, now(), now())`,
		id, s.Workspace().ID(), status, expires)
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func TestSurfaceApprovalsLapseAndDecideOnce(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	q := New(s.Q())
	now := time.Now().UTC()
	live := insertApproval(t, pool, s, "pending", now.Add(time.Hour))
	insertApproval(t, pool, s, "pending", now.Add(-time.Hour))
	nowTz := pgtype.Timestamptz{Time: now, Valid: true}
	count := func(status string) int64 {
		n, err := q.SurfaceApprovalCount(ctx, SurfaceApprovalCountParams{WorkspaceID: s.Workspace().ID(), Status: pgtype.Text{String: status, Valid: true}, Now: nowTz})
		if err != nil {
			t.Fatal(err)
		}
		return n
	}
	if count("pending") != 1 || count("expired") != 1 {
		t.Fatalf("pending %d expired %d", count("pending"), count("expired"))
	}
	decide := func() error {
		_, err := q.SurfaceDecideApproval(ctx, SurfaceDecideApprovalParams{
			NewStatus: "approved", DecidedBy: pgtype.Text{String: "user-2", Valid: true}, Now: nowTz,
			ExpiresAt: pgtype.Timestamptz{Time: now.Add(time.Hour), Valid: true},
			UpdatedAt: pgtype.Timestamp{Time: now, Valid: true}, ID: live, WorkspaceID: s.Workspace().ID(),
		})
		return err
	}
	if err := decide(); err != nil {
		t.Fatal(err)
	}
	if err := decide(); !errors.Is(err, pgx.ErrNoRows) {
		t.Fatalf("second decision: %v", err)
	}
}
