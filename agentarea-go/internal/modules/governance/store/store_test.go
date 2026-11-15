package store

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/schema"
)

func openPool(t *testing.T) *pgxpool.Pool {
	t.Helper()
	dsn := os.Getenv("AGENTAREA_TEST_POSTGRES_URL")
	if dsn == "" {
		t.Skip("AGENTAREA_TEST_POSTGRES_URL is not set")
	}
	sqlDB, err := schema.Open(dsn)
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Migrate(context.Background(), sqlDB, schema.Core()); err != nil {
		t.Fatal(err)
	}
	_ = sqlDB.Close()
	pool, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return pool
}

func workspace(t *testing.T, pool *pgxpool.Pool) db.Session {
	t.Helper()
	id := uuid.NewString()
	slug := "ws-" + id[:8]
	if _, err := pool.Exec(context.Background(),
		`INSERT INTO workspaces (id, name, owner_user_id, slug) VALUES ($1, 'W', 'owner', $2)`, id, slug); err != nil {
		t.Fatal(err)
	}
	ws, err := scope.NewWorkspace(id, slug)
	if err != nil {
		t.Fatal(err)
	}
	return db.NewSession(ws, pool)
}

func ptr[T any](v T) *T { return &v }

func TestPoliciesCRUDIsWorkspaceScoped(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var p Policies
	now := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	params := wirejson.Object{{Key: "amount_usd", Value: "10.00"}, {Key: "period", Value: "month"}}
	r := domain.Rule{SubjectType: "workspace", SubjectID: s.Workspace().ID(), Target: "spend", Effect: "cap", Params: params, Enabled: true, Priority: 7}
	id := uuid.New()
	created, err := p.Create(ctx, s, id, "owner", r, now)
	if err != nil {
		t.Fatal(err)
	}
	if created.ID != id.String() || created.Priority != 7 || created.Condition != nil {
		t.Fatalf("created %+v", created)
	}
	if amount, _ := wirejsonGet(created.Params, "amount_usd"); amount != "10.00" {
		t.Fatalf("params %#v", created.Params)
	}
	if _, found, err := p.Get(ctx, other, id); err != nil || found {
		t.Fatalf("other workspace sees the rule: %v %v", found, err)
	}
	got, found, err := p.Get(ctx, s, id)
	if err != nil || !found || got.Target != "spend" {
		t.Fatalf("get %+v %v %v", got, found, err)
	}

	second := r
	second.Target, second.Effect, second.Params, second.Priority = "tool:rm", "deny", wirejson.Object{}, 1
	if _, err := p.Create(ctx, s, uuid.New(), "owner", second, now); err != nil {
		t.Fatal(err)
	}
	all, err := p.List(ctx, s, Filter{})
	if err != nil || len(all) != 2 || all[0].Priority != 1 {
		t.Fatalf("list ordered by priority: %+v %v", all, err)
	}
	caps, err := p.List(ctx, s, Filter{Effect: ptr("cap"), Enabled: ptr(true)})
	if err != nil || len(caps) != 1 {
		t.Fatalf("filter %+v %v", caps, err)
	}
	if none, _ := p.List(ctx, other, Filter{}); len(none) != 0 {
		t.Fatalf("other workspace lists %d", len(none))
	}

	if _, ok, _ := p.Update(ctx, other, id, Patch{Enabled: ptr(false)}, now); ok {
		t.Fatal("other workspace updated the rule")
	}
	up, ok, err := p.Update(ctx, s, id, Patch{Enabled: ptr(false), Priority: ptr(int64(9))}, now.Add(time.Hour))
	if err != nil || !ok || up.Enabled || up.Priority != 9 || up.Target != "spend" {
		t.Fatalf("update %+v %v %v", up, ok, err)
	}
	var updatedAt, createdAt time.Time
	if err := pool.QueryRow(ctx, `SELECT created_at, updated_at FROM policies WHERE id = $1`, id).Scan(&createdAt, &updatedAt); err != nil {
		t.Fatal(err)
	}
	if !createdAt.Equal(now) || !updatedAt.Equal(now.Add(time.Hour)) {
		t.Fatalf("stamps %v %v", createdAt, updatedAt)
	}

	if gone, _ := p.Delete(ctx, other, id); gone {
		t.Fatal("other workspace deleted the rule")
	}
	if gone, err := p.Delete(ctx, s, id); err != nil || !gone {
		t.Fatalf("delete %v %v", gone, err)
	}
	if gone, _ := p.Delete(ctx, s, id); gone {
		t.Fatal("deleted twice")
	}
}

func wirejsonGet(v any, key string) (any, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		return nil, false
	}
	return o.Get(key)
}

func TestAuditInsertQueryAndCursor(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s, other := workspace(t, pool), workspace(t, pool)
	var a Audit
	base := time.Date(2026, 3, 1, 12, 0, 0, 0, time.UTC)
	ids := make([]string, 3)
	for i := range ids {
		ids[i] = uuid.NewString()
		e := domain.AuditEvent{ID: ids[i], ActorID: "u", ActorType: "user", WorkspaceID: s.Workspace().ID(),
			SourceIP: ptr("10.0.0.1"), Action: "governance_policy.create", ResourceType: "governance_policy",
			ResourceID: ptr("r" + string(rune('0'+i))), Metadata: map[string]any{"k": i}}
		if i == 2 {
			e.Action = "secret.create"
			e.Changes = []map[string]any{{"field": "value"}}
		}
		if err := a.Insert(ctx, s.Q(), e, base.Add(time.Duration(i)*time.Minute)); err != nil {
			t.Fatal(err)
		}
	}
	page, err := a.Query(ctx, s, domain.AuditQuery{Limit: 2})
	if err != nil || len(page) != 2 || page[0].ID != ids[2] || page[1].ID != ids[1] {
		t.Fatalf("newest first: %+v %v", page, err)
	}
	if page[0].SourceIP == nil || *page[0].SourceIP != "10.0.0.1" || string(page[0].RawChanges) == "" {
		t.Fatalf("row %+v", page[0])
	}
	c := [16]byte(uuid.MustParse(page[1].ID))
	rest, err := a.Query(ctx, s, domain.AuditQuery{Limit: 2, Cursor: &c})
	if err != nil || len(rest) != 1 || rest[0].ID != ids[0] {
		t.Fatalf("after cursor: %+v %v", rest, err)
	}
	since := base.Add(30 * time.Second)
	filtered, err := a.Query(ctx, s, domain.AuditQuery{Limit: 50, Action: ptr("governance_policy.create"), Since: &since})
	if err != nil || len(filtered) != 1 || filtered[0].ID != ids[1] {
		t.Fatalf("filtered %+v %v", filtered, err)
	}
	foreign := [16]byte(uuid.MustParse(ids[0]))
	if _, err := a.Query(ctx, other, domain.AuditQuery{Limit: 50, Cursor: &foreign}); !errors.Is(err, ErrUnknownCursor) {
		t.Fatalf("cursor from another workspace: %v", err)
	}
	if none, _ := a.Query(ctx, other, domain.AuditQuery{Limit: 50}); len(none) != 0 {
		t.Fatalf("other workspace reads %d events", len(none))
	}
}

func TestAuditInsertOnce(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var a Audit
	e := domain.AuditEvent{ID: uuid.NewString(), ActorID: "u", ActorType: "agent", WorkspaceID: s.Workspace().ID(), Action: "task.cancel", ResourceType: "task"}
	for i, want := range []bool{true, false} {
		got, err := a.InsertOnce(ctx, s.Q(), e)
		if err != nil || got != want {
			t.Fatalf("insert %d: %v %v", i, got, err)
		}
	}
	rows, err := a.Query(ctx, s, domain.AuditQuery{Limit: 50})
	if err != nil || len(rows) != 1 || rows[0].CreatedAt.IsZero() || rows[0].SourceIP != nil {
		t.Fatalf("rows %+v %v", rows, err)
	}
}

func TestAuditResourcePageCountsAndPages(t *testing.T) {
	ctx := context.Background()
	pool := openPool(t)
	s := workspace(t, pool)
	var a Audit
	base := time.Date(2026, 3, 1, 12, 0, 0, 0, time.UTC)
	ids := make([]string, 4)
	for i := range ids {
		ids[i] = uuid.NewString()
		e := domain.AuditEvent{ID: ids[i], ActorID: "u", ActorType: "user", WorkspaceID: s.Workspace().ID(),
			Action: "approval.approved", ResourceType: "task", ResourceID: ptr(uuid.NewString()), Metadata: map[string]any{"tool": "t"}}
		switch i {
		case 1:
			e.Action = "approval.denied"
		case 2:
			e.ResourceID = nil
		case 3:
			e.Action = "task.cancel"
		}
		if err := a.Insert(ctx, s.Q(), e, base.Add(time.Duration(i)*time.Minute)); err != nil {
			t.Fatal(err)
		}
	}
	actions := []string{"approval.approved", "approval.denied"}
	page, total, err := a.ResourcePage(ctx, s, "task", actions, 1, 0)
	if err != nil || total != 2 || len(page) != 1 || page[0].ID != ids[1] || string(page[0].RawMetadata) == "" {
		t.Fatalf("first page %+v %d %v", page, total, err)
	}
	rest, _, err := a.ResourcePage(ctx, s, "task", actions, 1, 1)
	if err != nil || len(rest) != 1 || rest[0].ID != ids[0] || rest[0].ResourceID == nil {
		t.Fatalf("second page %+v %v", rest, err)
	}
}
